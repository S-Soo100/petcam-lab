import 'server-only';

import { NextResponse } from 'next/server';

import { supabaseAdmin } from '@/lib/supabase';
import type { TutorialAccess } from '@/lib/labelingTutorial';

// 튜토리얼 접근 게이트 — server-only(DB 접근). 결정 로직은 순수 함수로 분리해
// 테스트하고(decideTutorialAccess), DB 래퍼(getTutorialAccess)가 그걸 호출한다.
// clipPerms.ts 는 이 모듈을 import 하지만 이 모듈은 clipPerms 를 import 하지 않는다
// (단방향 → 순환 없음).

export interface ActiveTutorial {
  setId: string;
  version: string;
  title: string;
  lessonCount: number;
}

// active set + lesson 수. active 없음/lesson<5 는 호출부에서 fail closed(설계 §5.7).
export async function loadActiveTutorial(): Promise<ActiveTutorial | null> {
  const { data, error } = await supabaseAdmin
    .from('labeling_tutorial_sets')
    .select('id, version, title')
    .eq('status', 'active')
    .limit(1);
  if (error || !(data ?? [])[0]) return null;
  const set = data![0];
  const { count } = await supabaseAdmin
    .from('labeling_tutorial_lessons')
    .select('id', { count: 'exact', head: true })
    .eq('tutorial_set_id', set.id);
  return {
    setId: set.id as string,
    version: set.version as string,
    title: set.title as string,
    lessonCount: count ?? 0,
  };
}

export interface TutorialProgressState {
  completed: boolean;
  waived: boolean;
  completedLessons: number;
}

// 순수 결정 — DB 결과를 접근 상태 하나로 접는다(단위 테스트 대상).
// owner 는 required=false(면제·preview)이되 실제 진행 상태를 표시한다.
// active 없음/불완전이면 labeler 는 required=true(준비 중 차단), owner 는 false.
export function decideTutorialAccess(input: {
  activeComplete: boolean;
  isOwner: boolean;
  progress: TutorialProgressState | null;
}): TutorialAccess {
  const total = 5 as const;
  if (!input.activeComplete) {
    return {
      required: !input.isOwner,
      status: 'unavailable',
      completed_lessons: 0,
      total_lessons: total,
    };
  }
  const p = input.progress;
  const completedLessons = p?.completed ? 5 : p?.completedLessons ?? 0;
  if (p?.waived) {
    return { required: false, status: 'waived', completed_lessons: completedLessons, total_lessons: total };
  }
  if (p?.completed) {
    return { required: false, status: 'completed', completed_lessons: 5, total_lessons: total };
  }
  if (input.isOwner) {
    return {
      required: false,
      status: p ? 'in_progress' : 'not_started',
      completed_lessons: completedLessons,
      total_lessons: total,
    };
  }
  if (p) {
    return { required: true, status: 'in_progress', completed_lessons: completedLessons, total_lessons: total };
  }
  return { required: true, status: 'not_started', completed_lessons: 0, total_lessons: total };
}

// 인증된 사용자의 튜토리얼 접근 상태(설계 §11 access 계약).
export async function getTutorialAccess(userId: string, isOwner: boolean): Promise<TutorialAccess> {
  const active = await loadActiveTutorial();
  const activeComplete = Boolean(active) && (active as ActiveTutorial).lessonCount >= 5;
  if (!activeComplete) {
    return decideTutorialAccess({ activeComplete: false, isOwner, progress: null });
  }
  const setId = (active as ActiveTutorial).setId;
  const { data } = await supabaseAdmin
    .from('labeling_tutorial_progress')
    .select('current_run_no, completed_at, waived_at')
    .eq('tutorial_set_id', setId)
    .eq('user_id', userId)
    .limit(1);
  const row = (data ?? [])[0];
  let progress: TutorialProgressState | null = null;
  if (row) {
    progress = {
      completed: Boolean(row.completed_at),
      waived: Boolean(row.waived_at),
      completedLessons: await countCompleted(setId, userId, row.current_run_no as number),
    };
  }
  return decideTutorialAccess({ activeComplete: true, isOwner, progress });
}

async function countCompleted(setId: string, userId: string, runNo: number): Promise<number> {
  const { count } = await supabaseAdmin
    .from('labeling_tutorial_attempts')
    .select('id', { count: 'exact', head: true })
    .eq('tutorial_set_id', setId)
    .eq('user_id', userId)
    .eq('run_no', runNo)
    .eq('stage', 'completed');
  return count ?? 0;
}

// production 게이트: 통과면 null, 미완료 labeler 면 403 tutorial_required(설계 §8).
// owner 는 이 함수를 거치지 않는다(호출부에서 bypass).
export async function tutorialGateResponse(userId: string): Promise<NextResponse | null> {
  const access = await getTutorialAccess(userId, false);
  if (!access.required) return null;
  return NextResponse.json({ detail: 'tutorial_required' }, { status: 403 });
}
