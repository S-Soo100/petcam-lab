import { NextRequest, NextResponse } from 'next/server';

import { loadClipWithPerms } from '@/lib/clipPerms';
import { GroundTruthValidationError, validateGroundTruth } from '@/lib/labelingV2';
import { supabaseAdmin } from '@/lib/supabase';
import {
  databaseError,
  loadLatestVlmPrediction,
  loadOwnSession,
  mapLickTarget,
} from '../../_helpers';

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
    if (sessionError) throw new Error(sessionError.message);

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
