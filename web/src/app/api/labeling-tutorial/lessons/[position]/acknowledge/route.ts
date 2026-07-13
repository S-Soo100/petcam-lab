import { NextRequest, NextResponse } from 'next/server';

import { requireLabelingAccess } from '@/lib/labelingAccess';
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

// POST /api/labeling-tutorial/lessons/[position]/acknowledge
// 피드백 확인 → lesson 완료. 다섯 번째면 같은 RPC transaction 에서 progress 완료(설계 §11).
// 이미 completed 면 그대로 반환(idempotent, 설계 §13).
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

    const runNo = await currentRunNo(setId, userId);
    const attempt = await loadAttempt(setId, lesson.id, userId, runNo);
    if (!attempt || (attempt.stage !== 'review_submitted' && attempt.stage !== 'completed')) {
      return NextResponse.json(
        { detail: '먼저 VLM 검수를 제출해 해설을 확인해야 해.' },
        { status: 409 },
      );
    }

    const { data, error } = await supabaseAdmin.rpc('fn_acknowledge_tutorial_lesson', {
      p_attempt_id: attempt.id,
      p_user_id: userId,
    });
    if (error) throw new Error(error.message);

    const result = data as { tutorial_completed?: boolean } | null;
    return NextResponse.json({ tutorial_completed: Boolean(result?.tutorial_completed) });
  } catch (cause) {
    return databaseUnavailable('labeling tutorial acknowledge', cause);
  }
}
