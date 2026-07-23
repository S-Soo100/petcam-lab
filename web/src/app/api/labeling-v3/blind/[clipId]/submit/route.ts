import { NextRequest, NextResponse } from 'next/server';

import { supabaseAdmin } from '@/lib/supabase';
import {
  GroundTruthValidationError,
  validateGroundTruth,
  type GroundTruthInput,
} from '@/lib/labelingV2';
import {
  BLIND_COMPARATOR_VERSION,
  canonicalSubmissionPair,
  compareBlindSubmissions,
  validateBlindSubmissionInput,
  type BlindDecision,
  type BlindReasonCode,
  type BlindSubmissionInput,
} from '@/lib/motionBlindReview';
import {
  blindBadRequest,
  blindDatabaseError,
  blindRpcErrorResponse,
  isValidUuid,
  requireBlindLabeler,
} from '@/lib/motionBlindReviewServer';
import { getAssignedBlindClip, parseCohortScope } from '../../_access';

export const runtime = 'nodejs';

// POST /api/labeling-v3/blind/[clipId]/submit — 최초 제출 + 자동 합의 finalize(설계 §5.3).
//
// 흐름: submit RPC 가 immutable 제출 저장 + (있으면) 상대 제출 content 를 서버에게만 반환 →
// 서버가 versioned pure comparator 로 비교 → finalize RPC 로 digest·버전 검증 후 consensus 멱등
// 저장 → 브라우저에는 { status, differing_fields } 만 반환. 상대 decision/GT/note/id/digest/lease
// 는 절대 브라우저 응답에 담지 않는다(설계 §5.1).

const MAX_BODY_BYTES = 64 * 1024;
const DECISIONS = new Set<BlindDecision>(['label', 'hold', 'exclude']);
const REASON_CODES = new Set<BlindReasonCode>([
  'behavior_data',
  'ambiguous',
  'gecko_absent',
  'capture_error',
  'media_error',
]);
const ALLOWED_KEYS = new Set(['decision', 'initial_gt', 'note', 'reason_code', 'lease_token', 'cohort_id']);

// GT jsonb 화이트리스트(주입 차단). gt 라우트와 동일 계약.
function sanitizeGroundTruth(gt: GroundTruthInput): GroundTruthInput {
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

interface SubmitRpcRow {
  own_submission_id: string;
  own_digest: string;
  is_duplicate: boolean;
  peer_present: boolean;
  peer_submission_id: string | null;
  peer_digest: string | null;
  peer_decision: BlindDecision | null;
  peer_reason_code: BlindReasonCode | null;
  peer_initial_gt: GroundTruthInput | null;
  peer_note: string | null;
}

export async function POST(req: NextRequest, { params }: { params: { clipId: string } }) {
  const access = await requireBlindLabeler(req);
  if (!access.ok) return access.response;
  const { userId } = access;

  if (!isValidUuid(params.clipId)) return blindBadRequest('잘못된 clip id');

  const declared = req.headers.get('content-length');
  if (declared && Number(declared) > MAX_BODY_BYTES) {
    return NextResponse.json({ detail: '요청이 너무 커.', code: 'payload_too_large' }, { status: 413 });
  }
  let rawText: string;
  try {
    rawText = await req.text();
  } catch {
    return blindBadRequest('본문을 읽을 수 없어.');
  }
  if (Buffer.byteLength(rawText, 'utf8') > MAX_BODY_BYTES) {
    return NextResponse.json({ detail: '요청이 너무 커.', code: 'payload_too_large' }, { status: 413 });
  }

  let body: Record<string, unknown>;
  try {
    const parsed = JSON.parse(rawText || '{}');
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
      return blindBadRequest('본문이 올바르지 않아.');
    }
    body = parsed as Record<string, unknown>;
  } catch {
    return blindBadRequest('본문이 올바르지 않아.');
  }
  for (const key of Object.keys(body)) {
    if (!ALLOWED_KEYS.has(key)) return blindBadRequest('허용되지 않은 필드가 있어.');
  }

  const decision = body.decision as BlindDecision;
  const reasonCode = body.reason_code as BlindReasonCode;
  if (!DECISIONS.has(decision)) return blindBadRequest('판정이 올바르지 않아.');
  if (!REASON_CODES.has(reasonCode)) return blindBadRequest('사유가 올바르지 않아.');
  const note = body.note == null ? null : body.note;
  if (note !== null && (typeof note !== 'string' || note.length > 2000)) {
    return blindBadRequest('메모는 2,000자 이하 텍스트여야 해.');
  }
  const leaseToken = body.lease_token;
  if (typeof leaseToken !== 'string' || !isValidUuid(leaseToken)) {
    return blindBadRequest('lease token 이 올바르지 않아.');
  }
  const cohortId = body.cohort_id == null ? null : String(body.cohort_id);
  const scope = parseCohortScope(cohortId);
  if (!scope) return blindBadRequest('잘못된 cohort id');

  // 배정 확인이 GT·RPC 보다 먼저(하드닝). 여기서 실제 clip duration 을 얻고, 미배정·잘못된 cohort·
  // 닫힌 canary·미존재 clip 은 존재를 드러내지 않는 404(not_assigned)로 일반화한다(설계 §7·§9).
  let assigned;
  try {
    assigned = await getAssignedBlindClip(userId, params.clipId, scope);
  } catch (cause) {
    return blindDatabaseError(cause);
  }
  if (!assigned) {
    return NextResponse.json({ detail: '대상을 찾을 수 없어.', code: 'not_assigned' }, { status: 404 });
  }

  // decision/GT shape(설계 §5.2): label 은 유효 GT 필수, 비-label 은 GT null. GT segment 는 실제
  // 영상 길이(assigned.durationSec) 안에서만 유효하다(관대한 3600 상한 제거).
  let sanitizedGt: GroundTruthInput | null = null;
  if (decision === 'label') {
    try {
      const gt = validateGroundTruth(body.initial_gt, assigned.durationSec);
      sanitizedGt = sanitizeGroundTruth(gt);
    } catch (error) {
      if (error instanceof GroundTruthValidationError) {
        return NextResponse.json({ detail: error.message, issues: error.issues }, { status: 400 });
      }
      return blindBadRequest('사람 판정 입력이 올바르지 않아.');
    }
  } else if (body.initial_gt != null) {
    return blindBadRequest('보류/제외에는 사람 판정을 넣을 수 없어.');
  }

  const ownInput: BlindSubmissionInput = {
    decision,
    initial_gt: sanitizedGt,
    note: (note as string | null) ?? null,
    reason_code: reasonCode,
  };
  try {
    validateBlindSubmissionInput(ownInput);
  } catch {
    return blindBadRequest('사람 판정 입력이 올바르지 않아.');
  }

  try {
    const first = await runSubmit(params.clipId, userId, scope, ownInput, leaseToken);
    if ('response' in first) return first.response;

    // 상대 제출이 없으면 대기 상태만 반환(상대 원문 노출 0).
    if (!first.row.peer_present) {
      return NextResponse.json({ status: 'awaiting_peer' });
    }

    const finalized = await compareAndFinalize(params.clipId, scope, ownInput, first.row, () =>
      runSubmit(params.clipId, userId, scope, ownInput, leaseToken),
    );
    return finalized;
  } catch (cause) {
    return blindDatabaseError(cause);
  }
}

type ScopeT = ReturnType<typeof parseCohortScope> & object;

async function runSubmit(
  clipId: string,
  userId: string,
  scope: ScopeT,
  input: BlindSubmissionInput,
  leaseToken: string,
): Promise<{ row: SubmitRpcRow } | { response: NextResponse }> {
  const { data, error } = await supabaseAdmin.rpc('fn_submit_motion_blind_review', {
    p_clip_id: clipId,
    p_reviewer_id: userId,
    p_cohort_kind: scope.cohortKind,
    p_cohort_id: scope.cohortId,
    p_decision: input.decision,
    p_reason_code: input.reason_code,
    p_initial_gt: input.initial_gt,
    p_note: input.note,
    p_lease_token: leaseToken,
  });
  if (error) {
    const mapped = blindRpcErrorResponse(error);
    return { response: mapped ?? blindDatabaseError(error) };
  }
  const row = (Array.isArray(data) ? data[0] : data) as SubmitRpcRow | undefined;
  if (!row) return { response: blindDatabaseError(new Error('empty submit result')) };
  return { row };
}

// 상대 제출을 받아 pure comparator 로 비교하고 finalize. stale digest(PT409)면 재조회(재-submit,
// 멱등) 후 한 번만 재시도한다(설계 §5.3). 응답에는 { status, differing_fields } 만.
async function compareAndFinalize(
  clipId: string,
  scope: ScopeT,
  ownInput: BlindSubmissionInput,
  row: SubmitRpcRow,
  reread: () => Promise<{ row: SubmitRpcRow } | { response: NextResponse }>,
): Promise<NextResponse> {
  let current = row;
  for (let attempt = 0; attempt < 2; attempt += 1) {
    let comparison;
    try {
      const peerInput: BlindSubmissionInput = {
        decision: current.peer_decision as BlindDecision,
        initial_gt: current.peer_initial_gt,
        note: current.peer_note,
        reason_code: current.peer_reason_code as BlindReasonCode,
      };
      comparison = compareBlindSubmissions(ownInput, peerInput);
    } catch (compErr) {
      // comparator 오류: 제출은 보존, consensus 는 awaiting 유지, 일반화된 대기 응답(설계 §8).
      console.error('[blind-review] comparator error', compErr);
      return NextResponse.json({ status: 'awaiting_peer' });
    }

    const [a, b] = canonicalSubmissionPair(
      { id: current.own_submission_id, digest: current.own_digest },
      { id: current.peer_submission_id as string, digest: current.peer_digest as string },
    );
    const { error } = await supabaseAdmin.rpc('fn_finalize_motion_blind_consensus', {
      p_clip_id: clipId,
      p_cohort_kind: scope.cohortKind,
      p_cohort_id: scope.cohortId,
      p_submission_a: a.id,
      p_submission_b: b.id,
      p_digest_a: a.digest,
      p_digest_b: b.digest,
      p_comparator_version: BLIND_COMPARATOR_VERSION,
      p_status: comparison.status,
      p_final_decision: comparison.final_decision,
      p_final_gt: comparison.final_gt,
      p_differing_fields: comparison.differing_fields,
    });
    if (!error) {
      return NextResponse.json({ status: comparison.status, differing_fields: comparison.differing_fields });
    }
    const code = (error as { code?: string }).code;
    if (code === 'PT409' && attempt === 0) {
      // 경합/stale digest: 재조회 후 한 번만 재시도.
      const again = await reread();
      if ('response' in again) return again.response;
      current = again.row;
      if (!current.peer_present) return NextResponse.json({ status: 'awaiting_peer' });
      continue;
    }
    return blindRpcErrorResponse(error) ?? blindDatabaseError(error);
  }
  // 재시도까지 stale 이면 대기로 접어 owner/운영이 감사하게 둔다.
  return NextResponse.json({ status: 'awaiting_peer' });
}
