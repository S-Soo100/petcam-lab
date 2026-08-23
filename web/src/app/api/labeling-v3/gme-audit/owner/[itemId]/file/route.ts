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

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const RANGE = /^bytes=(?:\d+-\d*|\d*-\d+)$/;
const CONTENT_RANGE = /^bytes (?:\d+-\d+|\*)\/\d+$/;

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

function ownerRequired() {
  return auditJson({ detail: 'Owner만 접근할 수 있어.', code: 'owner_required' }, 403);
}

function safeVideoHeaders(upstream: Response): Headers | null {
  const contentType = upstream.headers.get('content-type')?.split(';', 1)[0]?.trim().toLowerCase();
  if (!contentType?.startsWith('video/')) return null;
  const headers = new Headers({
    'Cache-Control': 'private, no-store, max-age=0',
    'Content-Type': contentType,
    'X-Content-Type-Options': 'nosniff',
  });
  const contentLength = upstream.headers.get('content-length');
  if (contentLength && /^\d+$/.test(contentLength)) headers.set('Content-Length', contentLength);
  const contentRange = upstream.headers.get('content-range');
  if (contentRange && CONTENT_RANGE.test(contentRange)) headers.set('Content-Range', contentRange);
  if (upstream.headers.get('accept-ranges')?.toLowerCase() === 'bytes') {
    headers.set('Accept-Ranges', 'bytes');
  }
  return headers;
}

export async function GET(
  req: NextRequest,
  { params }: { params: { itemId: string } },
) {
  const access = await requireProductionLabelingAccess(req);
  if (!access.ok) return withAuditNoStore(access.response);
  if (!access.isOwner) return ownerRequired();
  const range = req.headers.get('range');
  if (
    !isValidAuditItemId(params.itemId) ||
    Array.from(req.nextUrl.searchParams.keys()).length > 0 ||
    (range !== null && !RANGE.test(range))
  ) return auditInvalid();

  try {
    const itemResult = await supabaseAdmin
      .from('gme_negative_audit_items')
      .select('id, batch_id, clip_id')
      .eq('id', params.itemId)
      .limit(1);
    if (itemResult.error) throw itemResult.error;
    const item = firstExact(itemResult.data, ['id', 'batch_id', 'clip_id']);
    if (!item || item.id !== params.itemId || typeof item.batch_id !== 'string' || typeof item.clip_id !== 'string') {
      return auditJson({ detail: '대상을 찾을 수 없어.', code: 'not_found' }, 404);
    }

    const batchResult = await supabaseAdmin
      .from('gme_negative_audit_batches')
      .select('id')
      .eq('id', item.batch_id)
      .eq('owner_id', access.userId)
      .limit(1);
    if (batchResult.error) throw batchResult.error;
    const batch = firstExact(batchResult.data, ['id']);
    if (!batch || batch.id !== item.batch_id) {
      return auditJson({ detail: '대상을 찾을 수 없어.', code: 'not_found' }, 404);
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
      return auditJson({ detail: '점검이 종료됐어.', code: 'batch_closed' }, 410);
    }

    const submissionResult = await supabaseAdmin
      .from('gme_negative_audit_submissions')
      .select('id')
      .eq('item_id', params.itemId)
      .limit(1);
    if (submissionResult.error) throw submissionResult.error;
    if (!firstExact(submissionResult.data, ['id'])) {
      return auditJson({ detail: '대상을 찾을 수 없어.', code: 'not_found' }, 404);
    }

    const clipResult = await supabaseAdmin
      .from('motion_clips')
      .select('r2_key')
      .eq('id', item.clip_id)
      .limit(1);
    if (clipResult.error) throw clipResult.error;
    const clip = firstExact(clipResult.data, ['r2_key']);
    if (!clip || typeof clip.r2_key !== 'string' || clip.r2_key.trim().length === 0) {
      return auditJson({ detail: '영상을 재생할 수 없어.', code: 'media_unavailable' }, 410);
    }

    const upstreamUrl = await presignGet(clip.r2_key, AUDIT_MEDIA_TTL_SEC);
    const upstream = await fetch(upstreamUrl, {
      headers: range ? { Range: range } : {},
      redirect: 'error',
      cache: 'no-store',
    });
    if (upstream.status === 416) {
      const headers = new Headers({
        'Cache-Control': 'private, no-store, max-age=0',
        'X-Content-Type-Options': 'nosniff',
      });
      const contentRange = upstream.headers.get('content-range');
      if (contentRange && CONTENT_RANGE.test(contentRange)) headers.set('Content-Range', contentRange);
      return new Response(null, { status: 416, headers });
    }
    if (upstream.status !== 200 && upstream.status !== 206) return auditUnavailable();
    const headers = safeVideoHeaders(upstream);
    if (!headers) return auditUnavailable();
    return new Response(upstream.body, { status: upstream.status, headers });
  } catch {
    return auditUnavailable();
  }
}
