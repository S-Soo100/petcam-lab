import { NextRequest, NextResponse } from 'next/server';

import { getTutorialAccess, requireLabelingAccess } from '@/lib/labelingAccess';
import { loadActiveTutorial } from '@/lib/labelingTutorialGate';
import { supabaseAdmin } from '@/lib/supabase';
import { databaseUnavailable } from '@/lib/apiErrors';
import { currentRunNo, loadRunStages } from './_helpers';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

// GET /api/labeling-tutorial — 요약 화면용.
// 접근: owner 또는 labeler(owner 는 preview). 정답/prediction 은 여기서 노출하지 않는다.
export async function GET(req: NextRequest) {
  const access = await requireLabelingAccess(req);
  if (!access.ok) return access.response;
  const { userId, isOwner } = access;

  try {
    const tutorial = await getTutorialAccess(userId, isOwner);
    const active = await loadActiveTutorial();
    if (!active || active.lessonCount < 5) {
      // fail closed — 준비 중(설계 §5.7). 목록 없이 상태만.
      return NextResponse.json({ tutorial, set: null, lessons: [], current_run_no: 1 });
    }

    const { data: lessonRows, error } = await supabaseAdmin
      .from('labeling_tutorial_lessons')
      .select('id, position, title, learning_objective')
      .eq('tutorial_set_id', active.setId)
      .order('position', { ascending: true });
    if (error) throw new Error(error.message);

    const runNo = await currentRunNo(active.setId, userId);
    const stages = await loadRunStages(active.setId, userId, runNo);

    // 순서 잠금: 이전 lesson 이 completed 여야 다음이 available.
    let prevCompleted = true;
    const lessons = (lessonRows ?? []).map((row) => {
      const stage = stages.get(row.id as string);
      let state: 'locked' | 'available' | 'in_progress' | 'completed';
      if (stage === 'completed') state = 'completed';
      else if (stage === 'gt_locked' || stage === 'review_submitted') state = 'in_progress';
      else state = prevCompleted ? 'available' : 'locked';
      prevCompleted = stage === 'completed';
      return {
        position: row.position as number,
        title: row.title as string,
        learning_objective: row.learning_objective as string,
        state,
      };
    });

    return NextResponse.json({
      tutorial,
      set: { version: active.version, title: active.title },
      lessons,
      current_run_no: runNo,
    });
  } catch (cause) {
    return databaseUnavailable('labeling tutorial overview', cause);
  }
}
