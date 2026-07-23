import { NextRequest, NextResponse } from 'next/server';

import { requireOwner } from '@/lib/labelingAccess';
import { supabaseAdmin } from '@/lib/supabase';
import {
  GroundTruthValidationError,
  validateGroundTruth,
  type GroundTruthInput,
} from '@/lib/labelingV2';
import {
  blindBadRequest,
  blindDatabaseError,
  blindRpcErrorResponse,
  isValidUuid,
} from '@/lib/motionBlindReviewServer';
import { getOwnerClipDuration } from '../../../_access';

export const runtime = 'nodejs';

// POST /api/labeling-v3/blind/owner/[clipId]/resolve — owner 최종 판정(설계 §4.5·§8). owner 전용.
// choice a/b/new. new 는 유효 판정/GT 필요. conflict 만 대상(RPC PT426). expected_updated_at 로
// optimistic concurrency. 원본 resolution 은 append-only 이력으로 보존된다(RPC).
const MAX_BODY_BYTES = 64 * 1024;
const RFC3339 = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})$/;
const ALLOWED = new Set(['choice', 'final_decision', 'final_gt', 'reason', 'expected_updated_at']);

function sanitizeGt(gt: GroundTruthInput): GroundTruthInput {
  return {
    visibility: gt.visibility,
    primary_action: gt.primary_action,
    observed_actions: gt.observed_actions,
    segments: gt.segments,
    target: gt.target,
    human_confidence: gt.human_confidence,
    context_tags: gt.context_tags,
    activity_intensity: gt.activity_intensity,
    highlight_recommendation: gt.highlight_recommendation,
    enrichment_object: gt.enrichment_object,
    interaction_types: gt.interaction_types,
    note: gt.note,
  };
}

export async function POST(req: NextRequest, { params }: { params: { clipId: string } }) {
  const owner = await requireOwner(req);
  if (!owner.ok) return owner.response;
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
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) return blindBadRequest('본문이 올바르지 않아.');
    body = parsed as Record<string, unknown>;
  } catch {
    return blindBadRequest('본문이 올바르지 않아.');
  }
  for (const k of Object.keys(body)) if (!ALLOWED.has(k)) return blindBadRequest('허용되지 않은 필드가 있어.');

  const choice = body.choice;
  if (choice !== 'a' && choice !== 'b' && choice !== 'new') return blindBadRequest('판정 선택이 올바르지 않아.');
  const reason = body.reason == null ? null : body.reason;
  if (reason !== null && (typeof reason !== 'string' || reason.length > 2000)) {
    return blindBadRequest('사유는 2,000자 이하여야 해.');
  }
  const expected = body.expected_updated_at;
  if (typeof expected !== 'string' || !RFC3339.test(expected)) {
    return blindBadRequest('상태 버전이 올바르지 않아.');
  }

  let finalDecision: string | null = null;
  let finalGt: GroundTruthInput | null = null;
  if (choice === 'new') {
    finalDecision = body.final_decision as string;
    if (finalDecision !== 'label' && finalDecision !== 'hold' && finalDecision !== 'exclude') {
      return blindBadRequest('최종 판정이 올바르지 않아.');
    }
    if (finalDecision === 'label') {
      // owner final GT 도 실제 clip duration 으로 검증(하드닝: 3600 상한 제거). requireOwner 성공
      // 뒤에만 clip 을 조회한다. clip 이 없으면 판정 대상이 아니므로 404.
      let durationSec: number | null;
      try {
        durationSec = await getOwnerClipDuration(params.clipId);
      } catch (cause) {
        return blindDatabaseError(cause);
      }
      if (durationSec == null) {
        return NextResponse.json({ detail: '대상을 찾을 수 없어.', code: 'not_found' }, { status: 404 });
      }
      try {
        finalGt = sanitizeGt(validateGroundTruth(body.final_gt, durationSec));
      } catch (e) {
        if (e instanceof GroundTruthValidationError) {
          return NextResponse.json({ detail: e.message, issues: e.issues }, { status: 400 });
        }
        return blindBadRequest('사람 판정 입력이 올바르지 않아.');
      }
    } else if (body.final_gt != null) {
      return blindBadRequest('보류/제외에는 사람 판정을 넣을 수 없어.');
    }
  }

  try {
    const { data, error } = await supabaseAdmin.rpc('fn_resolve_motion_blind_consensus', {
      p_clip_id: params.clipId,
      p_cohort_kind: 'live',
      p_cohort_id: null,
      p_actor_id: owner.userId,
      p_choice: choice,
      p_final_decision: finalDecision,
      p_final_gt: finalGt,
      p_reason: reason,
      p_expected_updated_at: expected,
    });
    if (error) return blindRpcErrorResponse(error) ?? blindDatabaseError(error);
    const row = (Array.isArray(data) ? data[0] : data) as { status?: string } | undefined;
    return NextResponse.json({ status: row?.status ?? 'owner_resolved' });
  } catch (cause) {
    return blindDatabaseError(cause);
  }
}
