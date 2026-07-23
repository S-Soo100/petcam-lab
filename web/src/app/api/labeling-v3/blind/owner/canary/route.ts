import { NextRequest, NextResponse } from 'next/server';

import { requireOwner } from '@/lib/labelingAccess';
import { supabaseAdmin } from '@/lib/supabase';
import {
  blindBadRequest,
  blindDatabaseError,
  blindRpcErrorResponse,
  isValidUuid,
} from '@/lib/motionBlindReviewServer';

export const runtime = 'nodejs';

// POST /api/labeling-v3/blind/owner/canary — 격리 canary cohort 생성/종료(설계 §6.3·§10.2). owner 전용.
// create: test clip 1~20 + approved reviewer 2명 → cohort_kind=canary. close: status closed(row 삭제 아님).
const MAX_BODY_BYTES = 64 * 1024;
const ALLOWED = new Set(['action', 'cohort_id', 'label', 'group_id', 'clip_ids', 'reviewer_ids']);

function allUuids(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((v) => typeof v === 'string' && isValidUuid(v));
}

export async function POST(req: NextRequest) {
  const owner = await requireOwner(req);
  if (!owner.ok) return owner.response;

  const declared = req.headers.get('content-length');
  if (declared && Number(declared) > MAX_BODY_BYTES) {
    return NextResponse.json({ detail: '요청이 너무 커.', code: 'payload_too_large' }, { status: 413 });
  }
  let raw: string;
  try {
    raw = await req.text();
  } catch {
    return blindBadRequest('본문을 읽을 수 없어.');
  }
  if (Buffer.byteLength(raw, 'utf8') > MAX_BODY_BYTES) {
    return NextResponse.json({ detail: '요청이 너무 커.', code: 'payload_too_large' }, { status: 413 });
  }
  let body: Record<string, unknown>;
  try {
    const parsed = JSON.parse(raw || '{}');
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) return blindBadRequest('본문이 올바르지 않아.');
    body = parsed as Record<string, unknown>;
  } catch {
    return blindBadRequest('본문이 올바르지 않아.');
  }
  for (const k of Object.keys(body)) if (!ALLOWED.has(k)) return blindBadRequest('허용되지 않은 필드가 있어.');

  const action = body.action;
  if (action !== 'create' && action !== 'close') return blindBadRequest('canary 동작이 올바르지 않아.');

  if (action === 'close') {
    if (typeof body.cohort_id !== 'string' || !isValidUuid(body.cohort_id)) {
      return blindBadRequest('cohort id 가 올바르지 않아.');
    }
  } else {
    if (!allUuids(body.clip_ids) || (body.clip_ids as string[]).length < 1 || (body.clip_ids as string[]).length > 20) {
      return blindBadRequest('검증 clip 을 1~20개 골라줘.');
    }
    if (!allUuids(body.reviewer_ids) || (body.reviewer_ids as string[]).length !== 2) {
      return blindBadRequest('승인된 라벨러 두 명을 골라줘.');
    }
    if (typeof body.group_id !== 'string' || !isValidUuid(body.group_id)) {
      return blindBadRequest('그룹 id 가 올바르지 않아.');
    }
    if (body.label != null && (typeof body.label !== 'string' || body.label.length > 80)) {
      return blindBadRequest('라벨이 올바르지 않아.');
    }
  }

  try {
    const { data, error } = await supabaseAdmin.rpc('fn_manage_motion_blind_canary', {
      p_action: action,
      p_actor_id: owner.userId,
      p_cohort_id: action === 'close' ? body.cohort_id : null,
      p_label: action === 'create' ? (body.label ?? null) : null,
      p_group_id: action === 'create' ? body.group_id : null,
      p_clip_ids: action === 'create' ? body.clip_ids : null,
      p_reviewer_ids: action === 'create' ? body.reviewer_ids : null,
    });
    if (error) return blindRpcErrorResponse(error) ?? blindDatabaseError(error);
    const resolved = (Array.isArray(data) ? data[0] : data) as string | { fn_manage_motion_blind_canary?: string };
    const cohortId = typeof resolved === 'string' ? resolved : resolved?.fn_manage_motion_blind_canary ?? null;
    return NextResponse.json({ cohort_id: cohortId });
  } catch (cause) {
    return blindDatabaseError(cause);
  }
}
