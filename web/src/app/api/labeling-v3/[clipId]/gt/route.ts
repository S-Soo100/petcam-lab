import { NextRequest, NextResponse } from 'next/server';

import { requireProductionLabelingAccess } from '@/lib/labelingAccess';
import { GroundTruthValidationError, validateGroundTruth, type GroundTruthInput } from '@/lib/labelingV2';
import {
  motionLabelingDatabaseError,
  motionRpcErrorResponse,
  selectLatestSucceededPrediction,
  type VlmJobRow,
} from '@/lib/labelingV3Server';
import { supabaseAdmin } from '@/lib/supabase';

export const runtime = 'nodejs';

// POST /api/labeling-v3/[clipId]/gt — blind GT 잠금(설계 §5.2·§7.3).
//
// owner: 사전 label 결정 없이 어떤 media-ready clip 이든 잠근다(RPC 가 triage label 원자 전환).
// labeler: owner_decision='label' 인 clip 만(RPC PT403 → 404 은닉).
// prediction snapshot 은 서버가 clip_vlm_jobs 최신 성공 결과에서 고르고 클라이언트는 못 넘긴다.
// reviewer/stage/initial_gt/completion 은 전부 RPC 가 정한다(주입 차단).

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function badRequest(detail: string) {
  return NextResponse.json({ detail, code: 'invalid_request' }, { status: 400 });
}

// GT jsonb 를 알려진 12필드로만 화이트리스트 — 클라이언트가 prediction/stage/reviewed_by 등을
// GT 안에 심어도 세션에 새지 않게 한다(설계 §7.3 주입 차단).
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

export async function POST(req: NextRequest, { params }: { params: { clipId: string } }) {
  const access = await requireProductionLabelingAccess(req);
  if (!access.ok) return access.response;
  const { userId, isOwner } = access;
  if (!UUID.test(params.clipId)) return badRequest('잘못된 clip id');

  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return badRequest('본문이 올바르지 않아.');
  }

  try {
    // duration(세그먼트 검증) + 존재/미디어 확인.
    const { data: clipData, error: clipErr } = await supabaseAdmin
      .from('motion_clips')
      .select('duration_sec, r2_key')
      .eq('id', params.clipId)
      .limit(1);
    if (clipErr) throw clipErr;
    const clip = (clipData ?? [])[0] as { duration_sec: number; r2_key: string | null } | undefined;
    if (!clip) return NextResponse.json({ detail: '대상을 찾을 수 없어.', code: 'not_found' }, { status: 404 });
    if (clip.r2_key == null) {
      return NextResponse.json(
        { detail: '원본 영상이 없어 라벨링할 수 없어.', code: 'media_unavailable' },
        { status: 409 },
      );
    }

    // 기존 strict validator 재사용(변경 금지).
    let gt: GroundTruthInput;
    try {
      gt = validateGroundTruth(body, Number(clip.duration_sec) || 60);
    } catch (error) {
      if (error instanceof GroundTruthValidationError) {
        return NextResponse.json({ detail: error.message, issues: error.issues }, { status: 400 });
      }
      return badRequest((error as Error).message);
    }

    // prediction snapshot 은 서버가 고른다.
    const { data: jobs, error: jobErr } = await supabaseAdmin
      .from('clip_vlm_jobs')
      .select('id, status, result, completed_at')
      .eq('clip_id', params.clipId);
    if (jobErr) throw jobErr;
    const prediction = selectLatestSucceededPrediction((jobs ?? []) as VlmJobRow[]);

    const { data, error } = await supabaseAdmin.rpc('fn_lock_motion_clip_gt', {
      p_clip_id: params.clipId,
      p_reviewer_id: userId,
      p_is_owner: isOwner,
      p_gt: sanitizeGroundTruth(gt),
      p_prediction_snapshot: prediction,
    });
    if (error) return motionRpcErrorResponse(error) ?? motionLabelingDatabaseError(error);

    const session = (Array.isArray(data) ? data[0] : data) as {
      stage: string;
      prediction_snapshot: Record<string, unknown> | null;
    };
    const pred = session.prediction_snapshot ?? null;
    return NextResponse.json({
      stage: session.stage,
      prediction: pred,
      requires_vlm_review: pred != null,
    });
  } catch (cause) {
    return motionLabelingDatabaseError(cause);
  }
}
