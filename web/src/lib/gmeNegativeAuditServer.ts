import 'server-only';

import { NextRequest, NextResponse } from 'next/server';

import { mapAuditDetailRow, type AuditDetailItem } from '@/lib/gmeNegativeAudit';
import { supabaseAdmin } from '@/lib/supabase';

export const AUDIT_MAX_BODY_BYTES = 16 * 1024;
export const AUDIT_MEDIA_TTL_SEC = 300;
export const AUDIT_NO_STORE = 'private, no-store, max-age=0';

interface DbErrorLike {
  code?: string | null;
}

type AuditFailure = { ok: false; response: NextResponse };
type AuditSuccess<T> = { ok: true } & T;

export function auditJson(body: unknown, status = 200): NextResponse {
  return NextResponse.json(body, {
    status,
    headers: { 'Cache-Control': AUDIT_NO_STORE },
  });
}

export function withAuditNoStore(response: NextResponse): NextResponse {
  response.headers.set('Cache-Control', AUDIT_NO_STORE);
  return response;
}

function auditError(status: number, code: string, detail: string): NextResponse {
  return auditJson({ detail, code }, status);
}

export function auditInvalid(detail = '요청이 올바르지 않아.'): NextResponse {
  return auditError(400, 'invalid_request', detail);
}

export function auditNotAssigned(): NextResponse {
  return auditError(404, 'not_assigned', '대상을 찾을 수 없어.');
}

export function auditUnavailable(): NextResponse {
  return auditError(502, 'unavailable', '서비스를 사용할 수 없어. 잠시 후 다시 시도해.');
}

export function mapAuditRpcError(error: DbErrorLike | unknown): NextResponse {
  const code =
    typeof error === 'object' && error !== null && 'code' in error
      ? String((error as DbErrorLike).code ?? '')
      : '';
  switch (code) {
    case '22023':
      return auditInvalid();
    case 'PT403':
    case 'PT404':
      return auditNotAssigned();
    case 'PT410':
      return auditError(409, 'already_submitted', '이미 제출된 항목이야.');
    case 'PT409':
      return auditError(409, 'stale_revision', '판정이 변경됐어. 다시 불러와 정정해.');
    case 'PT427':
      return auditError(410, 'batch_closed', '점검이 종료됐어.');
    default:
      return auditUnavailable();
  }
}

export function isValidAuditItemId(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
    value,
  );
}

function firstRow(value: unknown): Record<string, unknown> | null {
  const row = Array.isArray(value) ? value[0] : value;
  return typeof row === 'object' && row !== null && !Array.isArray(row)
    ? (row as Record<string, unknown>)
    : null;
}

export async function requireAuditAssignment(
  reviewerId: string,
  itemId: string,
): Promise<AuditSuccess<{ row: Record<string, unknown> }> | AuditFailure> {
  if (!isValidAuditItemId(itemId)) return { ok: false, response: auditInvalid('잘못된 item id야.') };
  try {
    const { data, error } = await supabaseAdmin.rpc('fn_get_gme_negative_audit_item', {
      p_item_id: itemId,
      p_reviewer_id: reviewerId,
    });
    if (error) return { ok: false, response: mapAuditRpcError(error) };
    const row = firstRow(data);
    if (!row) return { ok: false, response: auditNotAssigned() };
    return { ok: true, row };
  } catch {
    return { ok: false, response: auditUnavailable() };
  }
}

async function readOwnRevision(
  reviewerId: string,
  itemId: string,
): Promise<AuditSuccess<{ revision: string | null }> | AuditFailure> {
  try {
    const correction = await supabaseAdmin
      .from('gme_negative_audit_corrections')
      .select('digest')
      .eq('item_id', itemId)
      .eq('reviewer_id', reviewerId)
      .order('created_at', { ascending: false })
      .order('id', { ascending: false })
      .limit(1);
    if (correction.error) return { ok: false, response: mapAuditRpcError(correction.error) };
    const corrected = firstRow(correction.data);
    if (typeof corrected?.digest === 'string' && corrected.digest.length > 0) {
      return { ok: true, revision: corrected.digest };
    }

    const submission = await supabaseAdmin
      .from('gme_negative_audit_submissions')
      .select('digest')
      .eq('item_id', itemId)
      .eq('reviewer_id', reviewerId)
      .limit(1);
    if (submission.error) return { ok: false, response: mapAuditRpcError(submission.error) };
    const initial = firstRow(submission.data);
    if (typeof initial?.digest === 'string' && initial.digest.length > 0) {
      return { ok: true, revision: initial.digest };
    }
    return { ok: true, revision: null };
  } catch {
    return { ok: false, response: auditUnavailable() };
  }
}

export async function loadAuditDetail(
  reviewerId: string,
  itemId: string,
): Promise<AuditSuccess<{ item: AuditDetailItem }> | AuditFailure> {
  const assigned = await requireAuditAssignment(reviewerId, itemId);
  if (!assigned.ok) return assigned;

  const hasSubmission = assigned.row.initial_verdict !== null;
  const revisionResult = hasSubmission
    ? await readOwnRevision(reviewerId, itemId)
    : ({ ok: true, revision: null } as const);
  if (!revisionResult.ok) return revisionResult;
  if (hasSubmission && revisionResult.revision === null) {
    return { ok: false, response: auditUnavailable() };
  }
  try {
    return {
      ok: true,
      item: mapAuditDetailRow({ ...assigned.row, revision: revisionResult.revision }),
    };
  } catch {
    return { ok: false, response: auditUnavailable() };
  }
}

export async function loadAuditMediaKey(
  reviewerId: string,
  itemId: string,
): Promise<AuditSuccess<{ r2Key: string }> | AuditFailure> {
  const assigned = await requireAuditAssignment(reviewerId, itemId);
  if (!assigned.ok) return assigned;

  try {
    // assignment RPC가 성공한 뒤에만 private clip identity와 r2_key를 단계적으로 읽는다.
    const item = await supabaseAdmin
      .from('gme_negative_audit_items')
      .select('clip_id')
      .eq('id', itemId)
      .eq('assigned_reviewer_id', reviewerId)
      .limit(1);
    if (item.error) return { ok: false, response: mapAuditRpcError(item.error) };
    const itemRow = firstRow(item.data);
    if (typeof itemRow?.clip_id !== 'string' || itemRow.clip_id.length === 0) {
      return { ok: false, response: auditUnavailable() };
    }

    const clip = await supabaseAdmin
      .from('motion_clips')
      .select('r2_key')
      .eq('id', itemRow.clip_id)
      .limit(1);
    if (clip.error) return { ok: false, response: mapAuditRpcError(clip.error) };
    const clipRow = firstRow(clip.data);
    if (typeof clipRow?.r2_key !== 'string' || clipRow.r2_key.trim().length === 0) {
      return {
        ok: false,
        response: auditError(410, 'media_unavailable', '영상을 재생할 수 없어.'),
      };
    }
    return { ok: true, r2Key: clipRow.r2_key };
  } catch {
    return { ok: false, response: auditUnavailable() };
  }
}

export async function readAuditJsonBody(
  req: NextRequest,
): Promise<AuditSuccess<{ value: unknown }> | AuditFailure> {
  const contentType = req.headers.get('content-type');
  const mediaType = contentType?.split(';', 1)[0]?.trim().toLowerCase();
  if (mediaType !== 'application/json') {
    try {
      await req.body?.cancel();
    } catch {
      // 이미 종료/취소된 request body는 그대로 400으로 접는다.
    }
    return { ok: false, response: auditInvalid() };
  }

  const declared = req.headers.get('content-length');
  if (declared !== null) {
    if (!/^\d+$/.test(declared)) {
      try {
        await req.body?.cancel();
      } catch {
        // invalid length가 public 400을 바꾸지 않게 한다.
      }
      return { ok: false, response: auditInvalid() };
    }
    if (Number(declared) > AUDIT_MAX_BODY_BYTES) {
      try {
        await req.body?.cancel();
      } catch {
        // early size rejection 뒤 transport cancellation 실패는 public 413을 바꾸지 않는다.
      }
      return {
        ok: false,
        response: auditError(413, 'payload_too_large', '요청이 너무 커.'),
      };
    }
  }

  const stream = req.body;
  if (!stream) return { ok: false, response: auditInvalid() };
  const reader = stream.getReader();
  const chunks: Uint8Array[] = [];
  let totalBytes = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      totalBytes += value.byteLength;
      if (totalBytes > AUDIT_MAX_BODY_BYTES) {
        try {
          await reader.cancel();
        } catch {
          // cancellation 실패가 size 판정을 바꾸거나 추가 buffering을 재개하지 않는다.
        }
        return {
          ok: false,
          response: auditError(413, 'payload_too_large', '요청이 너무 커.'),
        };
      }
      chunks.push(value);
    }
  } catch {
    try {
      await reader.cancel();
    } catch {
      // stream read failure는 stable 400으로만 공개한다.
    }
    return { ok: false, response: auditInvalid() };
  } finally {
    reader.releaseLock();
  }

  const bytes = new Uint8Array(totalBytes);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  try {
    const raw = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
    return { ok: true, value: JSON.parse(raw) };
  } catch {
    return { ok: false, response: auditInvalid() };
  }
}
