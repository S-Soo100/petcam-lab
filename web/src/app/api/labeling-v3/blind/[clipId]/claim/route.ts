import { NextRequest, NextResponse } from 'next/server';

import { supabaseAdmin } from '@/lib/supabase';
import {
  blindBadRequest,
  blindDatabaseError,
  blindRpcErrorResponse,
  isValidUuid,
  requireBlindLabeler,
} from '@/lib/motionBlindReviewServer';
import { parseCohortScope } from '../../_access';

export const runtime = 'nodejs';

// POST /api/labeling-v3/blind/[clipId]/claim — per-tab 30분 lease 발급/갱신(설계 §8).
//
// lease token 은 브라우저가 생성해 body 로 넘긴다. 서버는 토큰을 응답에 되돌려주지 않고(설계 계약)
// lease_expires_at 만 확인해준다. 같은 토큰이면 갱신, 다른 탭의 유효 lease 가 있으면 slot_in_use.
// reviewer id 는 bearer 에서만 — body 의 reviewer/group 을 신뢰하지 않는다.

const MAX_BODY_BYTES = 64 * 1024;
const ALLOWED_KEYS = new Set(['lease_token', 'cohort_id']);

export async function POST(req: NextRequest, { params }: { params: { clipId: string } }) {
  const access = await requireBlindLabeler(req);
  if (!access.ok) return access.response;
  const { userId } = access;

  if (!isValidUuid(params.clipId)) return blindBadRequest('잘못된 clip id');

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
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
      return blindBadRequest('본문이 올바르지 않아.');
    }
    body = parsed as Record<string, unknown>;
  } catch {
    return blindBadRequest('본문이 올바르지 않아.');
  }
  // exact-object allowlist: 모르는 key 는 거부.
  for (const key of Object.keys(body)) {
    if (!ALLOWED_KEYS.has(key)) return blindBadRequest('허용되지 않은 필드가 있어.');
  }

  const leaseToken = body.lease_token;
  if (typeof leaseToken !== 'string' || !isValidUuid(leaseToken)) {
    return blindBadRequest('lease token 이 올바르지 않아.');
  }
  const cohortId = body.cohort_id == null ? null : String(body.cohort_id);
  const scope = parseCohortScope(cohortId);
  if (!scope) return blindBadRequest('잘못된 cohort id');

  try {
    const { data, error } = await supabaseAdmin.rpc('fn_claim_motion_review_slot', {
      p_clip_id: params.clipId,
      p_reviewer_id: userId,
      p_cohort_kind: scope.cohortKind,
      p_cohort_id: scope.cohortId,
      p_new_token: leaseToken,
      p_existing_token: leaseToken,
    });
    if (error) return blindRpcErrorResponse(error) ?? blindDatabaseError(error);

    const row = (Array.isArray(data) ? data[0] : data) as
      | { lease_expires_at?: string }
      | undefined;
    // lease token 은 응답에 담지 않는다(설계 §92). 만료 시각만 확인해준다.
    return NextResponse.json({ lease_expires_at: row?.lease_expires_at ?? null });
  } catch (cause) {
    return blindDatabaseError(cause);
  }
}
