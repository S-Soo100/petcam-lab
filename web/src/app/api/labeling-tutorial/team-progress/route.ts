import { NextRequest, NextResponse } from 'next/server';

import { requireOwner } from '@/lib/labelingAccess';
import { loadActiveTutorial } from '@/lib/labelingTutorialGate';
import { supabaseAdmin } from '@/lib/supabase';
import { databaseUnavailable } from '@/lib/apiErrors';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

// GET /api/labeling-tutorial/team-progress — owner 전용(설계 §8·§10).
// 팀원별 진행 상태 + lesson별 mismatch dimension 수(comparison 의 review 그룹 개수).
// aggregate pass/fail 은 계산하지 않는다.
export async function GET(req: NextRequest) {
  const owner = await requireOwner(req);
  if (!owner.ok) return owner.response;

  try {
    const active = await loadActiveTutorial();
    if (!active || active.lessonCount < 5) {
      return NextResponse.json({ set: null, total_lessons: 5, items: [] });
    }
    const setId = active.setId;

    const [{ data: lessons }, { data: labelers }, { data: progressRows }, { data: attempts }] =
      await Promise.all([
        supabaseAdmin
          .from('labeling_tutorial_lessons')
          .select('id, position')
          .eq('tutorial_set_id', setId)
          .order('position', { ascending: true }),
        supabaseAdmin
          .from('labeler_applications')
          .select('user_id, display_name, email')
          .eq('status', 'approved')
          .order('display_name', { ascending: true }),
        supabaseAdmin
          .from('labeling_tutorial_progress')
          .select('user_id, current_run_no, completed_at, waived_at')
          .eq('tutorial_set_id', setId),
        supabaseAdmin
          .from('labeling_tutorial_attempts')
          .select('user_id, lesson_id, run_no, stage, comparison')
          .eq('tutorial_set_id', setId),
      ]);

    const lessonList = (lessons ?? []) as { id: string; position: number }[];
    const progressByUser = new Map(
      (progressRows ?? []).map((p) => [p.user_id as string, p]),
    );

    const items = (labelers ?? []).map((labeler) => {
      const userId = labeler.user_id as string;
      const prog = progressByUser.get(userId);
      const runNo = (prog?.current_run_no as number) ?? 1;
      const userAttempts = (attempts ?? []).filter(
        (a) => a.user_id === userId && a.run_no === runNo,
      );
      const attemptByLesson = new Map(userAttempts.map((a) => [a.lesson_id as string, a]));
      const completed = userAttempts.filter((a) => a.stage === 'completed').length;
      const status = prog?.waived_at
        ? 'waived'
        : prog?.completed_at
          ? 'completed'
          : prog
            ? 'in_progress'
            : 'not_started';
      const lessonsOut = lessonList.map((l) => {
        const att = attemptByLesson.get(l.id);
        const dims = (att?.comparison as { dimensions?: { group: string }[] } | null)?.dimensions;
        const mismatch = dims ? dims.filter((d) => d.group === 'review').length : null;
        return { position: l.position, mismatch_count: mismatch };
      });
      return {
        user_id: userId,
        display_name: labeler.display_name as string,
        email: labeler.email as string,
        status,
        completed_lessons: completed,
        lessons: lessonsOut,
      };
    });

    return NextResponse.json({
      set: { version: active.version, title: active.title },
      total_lessons: 5,
      items,
    });
  } catch (cause) {
    return databaseUnavailable('labeling tutorial team progress', cause);
  }
}
