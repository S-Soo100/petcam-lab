import { NextRequest, NextResponse } from 'next/server';

import { requireLabelingAccess } from '@/lib/labelingAccess';
import { databaseUnavailable } from '@/lib/apiErrors';
import {
  currentRunNo,
  loadActiveSetId,
  loadAttempt,
  loadLessonByPosition,
  loadLessonClip,
  loadRunStages,
  parsePosition,
} from '../../_helpers';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

// GET /api/labeling-tutorial/lessons/[position]
// 보안 핵심(설계 §8·§12·§13):
// - 제출 전: clip 메타·목표·tip·본인 attempt 만. reference/feedback key 자체를 생략.
// - GT 잠금 후: 고정 prediction_snapshot 공개.
// - VLM 검수 제출 후: reference·comparison·feedback 공개.
export async function GET(
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

    const runNo = await currentRunNo(setId, userId);
    const stages = await loadRunStages(setId, userId, runNo);
    const completedCount = Array.from(stages.values()).filter((s) => s === 'completed').length;
    const currentPosition = Math.min(completedCount + 1, 5);
    if (position > currentPosition) {
      // 순서 건너뛰기 — 현재 가능한 위치와 함께 409(설계 §13).
      return NextResponse.json(
        { detail: 'out_of_order', current_position: currentPosition },
        { status: 409 },
      );
    }

    const attempt = await loadAttempt(setId, lesson.id, userId, runNo);
    const clip = await loadLessonClip(lesson.clip_id);
    if (!clip) {
      return NextResponse.json({ detail: 'clip unavailable' }, { status: 404 });
    }
    const stage = attempt?.stage ?? 'draft';

    const body: Record<string, unknown> = {
      position,
      title: lesson.title,
      learning_objective: lesson.learning_objective,
      pre_submit_tip: lesson.pre_submit_tip,
      // 불변 tutorial set identity(하드닝 §3) — 브라우저 임시본 scope 격리에만 쓰는 비민감 식별자.
      set: { id: setId },
      clip: { id: clip.id, duration_sec: clip.duration_sec, started_at: clip.started_at },
      attempt: attempt
        ? {
            stage,
            submitted_gt: attempt.submitted_gt,
            submitted_vlm_review: attempt.submitted_vlm_review,
          }
        : null,
    };

    // GT 잠금 후에만 고정 VLM 공개.
    if (stage === 'gt_locked' || stage === 'review_submitted' || stage === 'completed') {
      body.prediction_snapshot = lesson.prediction_snapshot;
    }
    // VLM 검수 제출 후에만 reference/comparison/feedback — 그 전엔 key 자체를 넣지 않는다.
    if (stage === 'review_submitted' || stage === 'completed') {
      body.reference = { gt: lesson.reference_gt, vlm_review: lesson.reference_vlm_review };
      body.comparison = attempt?.comparison ?? null;
      body.feedback = lesson.feedback_content;
    }

    return NextResponse.json(body);
  } catch (cause) {
    return databaseUnavailable('labeling tutorial lesson', cause);
  }
}
