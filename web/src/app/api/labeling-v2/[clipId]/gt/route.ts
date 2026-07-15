import { NextRequest, NextResponse } from 'next/server';

import { loadClipWithPerms } from '@/lib/clipPerms';
import { GroundTruthValidationError, validateGroundTruth } from '@/lib/labelingV2';
import { supabaseAdmin } from '@/lib/supabase';
import {
  databaseError,
  loadLatestVlmPrediction,
  loadOwnSession,
  loadTriageEffectiveState,
  mapLickTarget,
} from '../../_helpers';
import { isHiddenFromLabelingQueue } from '@/lib/labelingTriage';

// 격리(pending)/스킵(skipped) clip 의 라벨링을 막을 때 쓰는 공통 409 응답.
// DB 가드 트리거(PT409)와 API 사전검사가 같은 계약을 공유한다. 내부 정보 미노출.
function triageQuarantinedResponse() {
  return NextResponse.json(
    { detail: '이 영상은 격리되어 라벨링할 수 없어.', code: 'triage_quarantined' },
    { status: 409 },
  );
}

export const runtime = 'nodejs';

export async function POST(
  req: NextRequest,
  { params }: { params: { clipId: string } },
) {
  const accessResult = await loadClipWithPerms(req, params.clipId);
  if (!accessResult.ok) return accessResult.response;
  const { clip, userId } = accessResult.access;

  let gt;
  try {
    const body = await req.json();
    gt = validateGroundTruth(body, Number(clip.duration_sec) || 60);
  } catch (error) {
    // detail 은 기존 client 호환용으로 유지하고, 필드별 인라인 오류용 issues[] 를 함께 준다(§6.3).
    if (error instanceof GroundTruthValidationError) {
      return NextResponse.json(
        { detail: error.message, issues: error.issues },
        { status: 400 },
      );
    }
    return NextResponse.json(
      { detail: (error as Error).message },
      { status: 400 },
    );
  }

  try {
    // 사전검사: 격리/스킵 상태면 저장 자체를 막는다(stale 상세 화면 방어, 설계 §9).
    // DB 가드 트리거는 최종 안전장치로 유지하고 이 검사로 대체하지 않는다.
    if (isHiddenFromLabelingQueue(await loadTriageEffectiveState(params.clipId))) {
      return triageQuarantinedResponse();
    }

    const existing = await loadOwnSession(params.clipId, userId);
    const prediction = existing?.initial_gt
      ? existing.prediction_snapshot
      : await loadLatestVlmPrediction(params.clipId);
    const now = new Date().toISOString();
    const stage = prediction ? 'gt_locked' : 'completed';
    const sessionPayload = {
      clip_id: params.clipId,
      reviewed_by: userId,
      initial_gt: existing?.initial_gt ?? gt,
      current_gt: gt,
      prediction_snapshot: prediction,
      stage: existing?.stage === 'completed' ? 'completed' : stage,
      completion_reason:
        existing?.completion_reason ?? (prediction ? null : 'no_prediction'),
      gt_locked_at: existing?.gt_locked_at ?? now,
      completed_at:
        existing?.completed_at ?? (prediction ? null : now),
      updated_at: now,
    };

    const sessionQuery = existing
      ? supabaseAdmin
          .from('clip_labeling_sessions')
          .update(sessionPayload)
          .eq('id', existing.id)
          .select('*')
          .single()
      : supabaseAdmin
          .from('clip_labeling_sessions')
          .insert(sessionPayload)
          .select('*')
          .single();
    const { data: session, error: sessionError } = await sessionQuery;
    if (sessionError) {
      // 가드 트리거 경합(사전검사 후 owner 가 격리) → 409. 원문 메시지는 노출하지 않는다.
      if ((sessionError as { code?: string }).code === 'PT409') {
        return triageQuarantinedResponse();
      }
      throw new Error(sessionError.message);
    }

    const lickTarget = mapLickTarget(gt.primary_action, gt.target);
    const { error: labelError } = await supabaseAdmin
      .from('behavior_labels')
      .upsert(
        {
          clip_id: params.clipId,
          labeled_by: userId,
          action: gt.primary_action,
          lick_target: lickTarget,
          note: gt.note,
          labeled_at: now,
        },
        { onConflict: 'clip_id,labeled_by' },
      );
    if (labelError) throw new Error(labelError.message);

    return NextResponse.json({
      session,
      prediction: session.prediction_snapshot,
      requires_vlm_review: Boolean(prediction),
    });
  } catch (error) {
    return databaseError(error);
  }
}
