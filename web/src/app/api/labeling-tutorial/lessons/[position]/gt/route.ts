import { NextRequest, NextResponse } from 'next/server';

import { requireLabelingAccess } from '@/lib/labelingAccess';
import { validateGroundTruth } from '@/lib/labelingV2';
import { deepEqualAnswer } from '@/lib/labelingTutorial';
import { supabaseAdmin } from '@/lib/supabase';
import { databaseUnavailable } from '@/lib/apiErrors';
import {
  ensureProgress,
  loadActiveSetId,
  loadAttempt,
  loadLessonByPosition,
  loadLessonClip,
  loadRunStages,
  parsePosition,
} from '../../../_helpers';

export const runtime = 'nodejs';

// POST /api/labeling-tutorial/lessons/[position]/gt
// 튜토리얼 Blind GT 잠금. production v2 와 달리 behavior_labels /
// clip_labeling_sessions 에 절대 쓰지 않는다(learning 시도와 운영 GT 분리, 설계 §1).
// 응답에 reference 를 넣지 않고 고정 VLM prediction_snapshot 만 반환(설계 §11).
// idempotent: 같은 payload 재전송 200, 다른 payload 409(설계 §13).
export async function POST(
  req: NextRequest,
  { params }: { params: { position: string } },
) {
  const access = await requireLabelingAccess(req);
  if (!access.ok) return access.response;
  const { userId } = access;

  const position = parsePosition(params.position);
  if (position === null) {
    return NextResponse.json({ detail: 'not found' }, { status: 404 });
  }

  try {
    const setId = await loadActiveSetId();
    if (!setId) return NextResponse.json({ detail: 'not found' }, { status: 404 });
    const lesson = await loadLessonByPosition(setId, position);
    if (!lesson) return NextResponse.json({ detail: 'not found' }, { status: 404 });
    const clip = await loadLessonClip(lesson.clip_id);
    if (!clip) return NextResponse.json({ detail: 'clip unavailable' }, { status: 404 });

    let gt;
    try {
      gt = validateGroundTruth(await req.json(), Number(clip.duration_sec) || 60);
    } catch (error) {
      return NextResponse.json({ detail: (error as Error).message }, { status: 400 });
    }

    const runNo = await ensureProgress(setId, userId);

    // 순서 강제: 이전 lesson 이 completed 여야 현재 GT 제출 가능(설계 §13).
    const stages = await loadRunStages(setId, userId, runNo);
    const completedCount = Array.from(stages.values()).filter((s) => s === 'completed').length;
    const currentPosition = Math.min(completedCount + 1, 5);
    const attempt = await loadAttempt(setId, lesson.id, userId, runNo);
    if (!attempt && position > currentPosition) {
      return NextResponse.json(
        { detail: 'out_of_order', current_position: currentPosition },
        { status: 409 },
      );
    }

    // 최초 GT 는 불변. 같은 값 재전송은 idempotent, 다른 값은 409(설계 §13).
    if (attempt?.submitted_gt) {
      if (!deepEqualAnswer(attempt.submitted_gt, gt)) {
        return NextResponse.json({ detail: 'gt_already_submitted' }, { status: 409 });
      }
      return NextResponse.json({ prediction_snapshot: lesson.prediction_snapshot });
    }

    const now = new Date().toISOString();
    const payload = {
      stage: 'gt_locked' as const,
      submitted_gt: gt,
      gt_locked_at: now,
      updated_at: now,
    };
    const query = attempt
      ? supabaseAdmin.from('labeling_tutorial_attempts').update(payload).eq('id', attempt.id)
      : supabaseAdmin.from('labeling_tutorial_attempts').insert({
          tutorial_set_id: setId,
          lesson_id: lesson.id,
          user_id: userId,
          run_no: runNo,
          ...payload,
        });
    const { error } = await query;
    if (error) throw new Error(error.message);

    return NextResponse.json({ prediction_snapshot: lesson.prediction_snapshot });
  } catch (cause) {
    return databaseUnavailable('labeling tutorial gt', cause);
  }
}
