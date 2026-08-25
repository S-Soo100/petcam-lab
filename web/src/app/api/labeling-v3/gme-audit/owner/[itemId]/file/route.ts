import { NextRequest } from 'next/server';

import {
  AUDIT_MEDIA_TTL_SEC,
  auditInvalid,
  auditJson,
  auditUnavailable,
  isValidAuditItemId,
  withAuditNoStore,
} from '@/lib/gmeNegativeAuditServer';
import { requireProductionLabelingAccess } from '@/lib/labelingAccess';
import { presignGet } from '@/lib/r2';
import { supabaseAdmin } from '@/lib/supabase';
import { InvalidOwnerPlaybackTokenError, verifyOwnerPlaybackToken } from '../../_playback-token';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const MAX_CHUNK_BYTES = 8 * 1024 * 1024;
const MAX_RANGE_DIGITS = 16;
const SATISFIED_CONTENT_RANGE = /^bytes ([0-9]{1,16})-([0-9]{1,16})\/([0-9]{1,16})$/;
const UNSATISFIED_CONTENT_RANGE = /^bytes \*\/([0-9]{1,16})$/;

type BoundedRange = {
  header: string;
  start: number | null;
  end: number | null;
  suffix: number | null;
};

function firstExact(value: unknown, keys: readonly string[]): Record<string, unknown> | null {
  const row = Array.isArray(value) ? value[0] : value;
  if (row === undefined || row === null) return null;
  if (typeof row !== 'object' || Array.isArray(row)) throw new Error('shape');
  const record = row as Record<string, unknown>;
  const actual = Object.keys(record).sort();
  const expected = [...keys].sort();
  if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) {
    throw new Error('keys');
  }
  return record;
}

function mediaHeaders(response: Response): Response {
  response.headers.set('Cache-Control', 'private, no-store, max-age=0');
  response.headers.set('Referrer-Policy', 'no-referrer');
  response.headers.set('X-Content-Type-Options', 'nosniff');
  return response;
}

function forbidden(): Response {
  return mediaHeaders(auditJson({ detail: '접근할 수 없어.', code: 'forbidden' }, 403));
}

function rangeNotSatisfiable(total?: number): Response {
  const response = new Response(null, { status: 416 });
  if (total !== undefined) response.headers.set('Content-Range', `bytes */${total}`);
  return mediaHeaders(response);
}

function safeInteger(raw: string): number | null {
  if (raw.length === 0 || raw.length > MAX_RANGE_DIGITS || !/^\d+$/.test(raw)) return null;
  const value = Number(raw);
  return Number.isSafeInteger(value) ? value : null;
}

function parseRange(raw: string | null): BoundedRange | null {
  if (raw === null) {
    return { header: `bytes=0-${MAX_CHUNK_BYTES - 1}`, start: 0, end: MAX_CHUNK_BYTES - 1, suffix: null };
  }
  const suffix = /^bytes=-(\d+)$/.exec(raw);
  if (suffix) {
    const length = safeInteger(suffix[1]);
    if (length === null || length < 1 || length > MAX_CHUNK_BYTES) return null;
    return { header: `bytes=-${length}`, start: null, end: null, suffix: length };
  }
  const absolute = /^bytes=(\d+)-(\d*)$/.exec(raw);
  if (!absolute) return null;
  const start = safeInteger(absolute[1]);
  if (start === null) return null;
  if (absolute[2] === '') {
    const end = start + MAX_CHUNK_BYTES - 1;
    if (!Number.isSafeInteger(end)) return null;
    return { header: `bytes=${start}-${end}`, start, end, suffix: null };
  }
  const end = safeInteger(absolute[2]);
  if (end === null || end < start || end - start + 1 > MAX_CHUNK_BYTES) return null;
  return { header: `bytes=${start}-${end}`, start, end, suffix: null };
}

async function cancelUpstream(upstream: Response): Promise<void> {
  try {
    await upstream.body?.cancel();
  } catch {
    // Provider cancellation failure never changes the safe public response.
  }
}

function parseSatisfiedRange(upstream: Response, requested: BoundedRange): {
  contentType: string;
  contentLength: number;
  contentRange: string;
} | null {
  const contentType = upstream.headers.get('content-type')?.split(';', 1)[0]?.trim().toLowerCase();
  const contentLengthRaw = upstream.headers.get('content-length');
  const contentRange = upstream.headers.get('content-range');
  if (!contentType?.startsWith('video/') || contentLengthRaw === null || contentRange === null) return null;
  const contentLength = safeInteger(contentLengthRaw);
  const match = SATISFIED_CONTENT_RANGE.exec(contentRange);
  if (contentLength === null || contentLength < 1 || contentLength > MAX_CHUNK_BYTES || !match) return null;
  const start = safeInteger(match[1]);
  const end = safeInteger(match[2]);
  const total = safeInteger(match[3]);
  if (start === null || end === null || total === null || end < start || total <= end) return null;
  if (end - start + 1 !== contentLength) return null;
  if (requested.suffix !== null) {
    const expectedStart = Math.max(total - requested.suffix, 0);
    const expectedLength = Math.min(requested.suffix, total);
    if (
      start !== expectedStart
      || end !== total - 1
      || contentLength !== expectedLength
    ) return null;
  } else if (
    requested.start === null
    || requested.end === null
    || start !== requested.start
    || end > requested.end
    || (end < requested.end && end !== total - 1)
  ) return null;
  return { contentType, contentLength, contentRange };
}

async function readExactBoundedBody(upstream: Response, expected: number): Promise<Uint8Array | null> {
  if (!upstream.body) return null;
  const reader = upstream.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > expected || total > MAX_CHUNK_BYTES) {
        await reader.cancel();
        return null;
      }
      chunks.push(value);
    }
  } catch {
    try { await reader.cancel(); } catch { /* stable 502 */ }
    return null;
  }
  if (total !== expected) return null;
  const body = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    body.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return body;
}

async function ownerIdentity(req: NextRequest, itemId: string): Promise<string | Response> {
  const tokens = req.nextUrl.searchParams.getAll('token');
  const keys = Array.from(req.nextUrl.searchParams.keys());
  if (tokens.length > 0) {
    if (tokens.length !== 1 || keys.length !== 1 || keys[0] !== 'token') return forbidden();
    try {
      return verifyOwnerPlaybackToken(tokens[0], itemId).ownerUserId;
    } catch (error) {
      if (error instanceof InvalidOwnerPlaybackTokenError) return forbidden();
      return forbidden();
    }
  }
  if (keys.length > 0) return mediaHeaders(auditInvalid());
  const access = await requireProductionLabelingAccess(req);
  if (!access.ok) return mediaHeaders(withAuditNoStore(access.response));
  if (!access.isOwner) return forbidden();
  return access.userId;
}

export async function GET(
  req: NextRequest,
  { params }: { params: { itemId: string } },
) {
  if (!isValidAuditItemId(params.itemId)) return mediaHeaders(auditInvalid());
  const identity = await ownerIdentity(req, params.itemId);
  if (identity instanceof Response) return identity;
  const requestedRange = parseRange(req.headers.get('range'));
  if (!requestedRange) return rangeNotSatisfiable();

  try {
    const itemResult = await supabaseAdmin
      .from('gme_negative_audit_items')
      .select('id, batch_id, clip_id')
      .eq('id', params.itemId)
      .limit(1);
    if (itemResult.error) throw itemResult.error;
    const item = firstExact(itemResult.data, ['id', 'batch_id', 'clip_id']);
    if (!item || item.id !== params.itemId || typeof item.batch_id !== 'string' || typeof item.clip_id !== 'string') {
      return mediaHeaders(auditJson({ detail: '대상을 찾을 수 없어.', code: 'not_found' }, 404));
    }

    const batchResult = await supabaseAdmin
      .from('gme_negative_audit_batches')
      .select('id')
      .eq('id', item.batch_id)
      .eq('owner_id', identity)
      .limit(1);
    if (batchResult.error) throw batchResult.error;
    const batch = firstExact(batchResult.data, ['id']);
    if (!batch || batch.id !== item.batch_id) {
      return mediaHeaders(auditJson({ detail: '대상을 찾을 수 없어.', code: 'not_found' }, 404));
    }

    const eventResult = await supabaseAdmin
      .from('gme_negative_audit_batch_events')
      .select('event_type')
      .eq('batch_id', item.batch_id)
      .order('created_at', { ascending: false })
      .order('id', { ascending: false })
      .limit(1);
    if (eventResult.error) throw eventResult.error;
    const event = firstExact(eventResult.data, ['event_type']);
    if (!event || event.event_type !== 'opened') {
      return mediaHeaders(auditJson({ detail: '점검이 종료됐어.', code: 'batch_closed' }, 410));
    }

    const submissionResult = await supabaseAdmin
      .from('gme_negative_audit_submissions')
      .select('id')
      .eq('item_id', params.itemId)
      .limit(1);
    if (submissionResult.error) throw submissionResult.error;
    if (!firstExact(submissionResult.data, ['id'])) {
      return mediaHeaders(auditJson({ detail: '대상을 찾을 수 없어.', code: 'not_found' }, 404));
    }

    const clipResult = await supabaseAdmin
      .from('motion_clips')
      .select('r2_key')
      .eq('id', item.clip_id)
      .limit(1);
    if (clipResult.error) throw clipResult.error;
    const clip = firstExact(clipResult.data, ['r2_key']);
    if (!clip || typeof clip.r2_key !== 'string' || clip.r2_key.trim().length === 0) {
      return mediaHeaders(auditJson({ detail: '영상을 재생할 수 없어.', code: 'media_unavailable' }, 410));
    }

    const upstreamUrl = await presignGet(clip.r2_key, AUDIT_MEDIA_TTL_SEC);
    const upstream = await fetch(upstreamUrl, {
      headers: { Range: requestedRange.header },
      redirect: 'error',
      cache: 'no-store',
    });
    if (upstream.status === 416) {
      const match = UNSATISFIED_CONTENT_RANGE.exec(upstream.headers.get('content-range') ?? '');
      const total = match ? safeInteger(match[1]) : null;
      await cancelUpstream(upstream);
      return total === null ? mediaHeaders(auditUnavailable()) : rangeNotSatisfiable(total);
    }
    if (upstream.status !== 206) {
      await cancelUpstream(upstream);
      return mediaHeaders(auditUnavailable());
    }
    const validated = parseSatisfiedRange(upstream, requestedRange);
    if (!validated) {
      await cancelUpstream(upstream);
      return mediaHeaders(auditUnavailable());
    }
    const body = await readExactBoundedBody(upstream, validated.contentLength);
    if (!body) return mediaHeaders(auditUnavailable());
    const headers = new Headers({
      'Content-Type': validated.contentType,
      'Content-Length': String(validated.contentLength),
      'Content-Range': validated.contentRange,
      'Accept-Ranges': 'bytes',
    });
    const responseBody = new ArrayBuffer(body.byteLength);
    new Uint8Array(responseBody).set(body);
    return mediaHeaders(new Response(responseBody, { status: 206, headers }));
  } catch {
    return mediaHeaders(auditUnavailable());
  }
}
