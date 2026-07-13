import { NextRequest, NextResponse } from 'next/server';

import { requireLabelingAccess } from '@/lib/labelingAccess';
import { validateVlmReview, type GroundTruthInput, type VlmReviewInput } from '@/lib/labelingV2';
import { compareTutorialAnswers, deepEqualAnswer } from '@/lib/labelingTutorial';
import { supabaseAdmin } from '@/lib/supabase';
import { databaseUnavailable } from '@/lib/apiErrors';
import {
  currentRunNo,
  loadActiveSetId,
  loadAttempt,
  loadLessonByPosition,
  parsePosition,
} from '../../../_helpers';

export const runtime = 'nodejs';

// POST /api/labeling-tutorial/lessons/[position]/vlm-review
// 최초 VLM 검수 제출 후에만 reference·comparison·feedback 를 공개(설계 §11·§12).
// comparison 은 서버 순수 함수로 계산해 attempt 에 불변 저장한다.
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

  let review: VlmReviewInput;
  try {
    review = validateVlmReview(await req.json());
  } catch (error) {
    return NextResponse.json({ detail: (error as Error).message }, { status: 400 });
  }

  try {
    const setId = await loadActiveSetId();
    if (!setId) return NextResponse.json({ detail: 'not found' }, { status: 404 });
    const lesson = await loadLessonByPosition(setId, position);
    if (!lesson) return NextResponse.json({ detail: 'not found' }, { status: 404 });

    const runNo = await currentRunNo(setId, userId);
    const attempt = await loadAttempt(setId, lesson.id, userId, runNo);
    if (!attempt?.submitted_gt) {
      return NextResponse.json(
        { detail: '먼저 blind GT를 잠그고 VLM 판정을 공개해야 해.' },
        { status: 409 },
      );
    }

    const reveal = (comparison: unknown) => ({
      reference: { gt: lesson.reference_gt, vlm_review: lesson.reference_vlm_review },
      comparison,
      feedback: lesson.feedback_content,
    });

    // 최초 review 는 불변. 같은 값 재전송 idempotent, 다른 값 409(설계 §13).
    if (attempt.submitted_vlm_review) {
      if (!deepEqualAnswer(attempt.submitted_vlm_review, review)) {
        return NextResponse.json({ detail: 'review_already_submitted' }, { status: 409 });
      }
      return NextResponse.json(reveal(attempt.comparison));
    }

    const comparison = compareTutorialAnswers(
      attempt.submitted_gt as unknown as GroundTruthInput,
      review,
      lesson.reference_gt as unknown as GroundTruthInput,
      lesson.reference_vlm_review as unknown as VlmReviewInput,
    );

    const now = new Date().toISOString();
    const { error } = await supabaseAdmin
      .from('labeling_tutorial_attempts')
      .update({
        stage: 'review_submitted',
        submitted_vlm_review: review,
        comparison,
        review_submitted_at: now,
        updated_at: now,
      })
      .eq('id', attempt.id);
    if (error) throw new Error(error.message);

    return NextResponse.json(reveal(comparison));
  } catch (cause) {
    return databaseUnavailable('labeling tutorial vlm review', cause);
  }
}
