import { supabaseAdmin } from '@/lib/supabase';
import { loadActiveTutorial } from '@/lib/labelingTutorialGate';

// 튜토리얼 API 공통 로더. 정답이 든 lesson row 를 그대로 반환하므로, 라우트가
// 응답 조립 시 stage 에 따라 노출 필드를 직접 골라야 한다(reference/feedback 미노출).

export function parsePosition(raw: string): number | null {
  const n = Number(raw);
  return Number.isInteger(n) && n >= 1 && n <= 5 ? n : null;
}

// active + lesson 5개 완비일 때만 setId. 불완전이면 null(fail closed).
export async function loadActiveSetId(): Promise<string | null> {
  const active = await loadActiveTutorial();
  return active && active.lessonCount >= 5 ? active.setId : null;
}

export interface TutorialLessonRow {
  id: string;
  tutorial_set_id: string;
  position: number;
  clip_id: string;
  title: string;
  learning_objective: string;
  pre_submit_tip: string | null;
  reference_gt: Record<string, unknown>;
  prediction_snapshot: Record<string, unknown>;
  reference_vlm_review: Record<string, unknown>;
  feedback_content: Record<string, unknown>;
}

export async function loadLessonByPosition(
  setId: string,
  position: number,
): Promise<TutorialLessonRow | null> {
  const { data, error } = await supabaseAdmin
    .from('labeling_tutorial_lessons')
    .select('*')
    .eq('tutorial_set_id', setId)
    .eq('position', position)
    .limit(1);
  if (error) throw new Error(error.message);
  return ((data ?? [])[0] as TutorialLessonRow | undefined) ?? null;
}

export interface TutorialProgressRow {
  tutorial_set_id: string;
  user_id: string;
  current_run_no: number;
  completed_at: string | null;
  waived_at: string | null;
}

export async function loadProgressRow(
  setId: string,
  userId: string,
): Promise<TutorialProgressRow | null> {
  const { data, error } = await supabaseAdmin
    .from('labeling_tutorial_progress')
    .select('tutorial_set_id, user_id, current_run_no, completed_at, waived_at')
    .eq('tutorial_set_id', setId)
    .eq('user_id', userId)
    .limit(1);
  if (error) throw new Error(error.message);
  return ((data ?? [])[0] as TutorialProgressRow | undefined) ?? null;
}

// 현재 run 번호(progress 없으면 1). attempt 조회·생성 기준.
export async function currentRunNo(setId: string, userId: string): Promise<number> {
  const progress = await loadProgressRow(setId, userId);
  return progress?.current_run_no ?? 1;
}

// GT 잠금 시 progress 를 보장(없으면 생성) 후 current_run_no 반환. 튜토리얼 시작점.
// 동시 요청 경합으로 insert 가 충돌하면 재조회해 기존 run 을 쓴다.
export async function ensureProgress(setId: string, userId: string): Promise<number> {
  const existing = await loadProgressRow(setId, userId);
  if (existing) return existing.current_run_no;
  const { data, error } = await supabaseAdmin
    .from('labeling_tutorial_progress')
    .insert({ tutorial_set_id: setId, user_id: userId })
    .select('current_run_no')
    .single();
  if (error) {
    const reload = await loadProgressRow(setId, userId);
    if (reload) return reload.current_run_no;
    throw new Error(error.message);
  }
  return (data?.current_run_no as number) ?? 1;
}

export interface TutorialAttemptRow {
  id: string;
  lesson_id: string;
  run_no: number;
  stage: 'draft' | 'gt_locked' | 'review_submitted' | 'completed';
  submitted_gt: Record<string, unknown> | null;
  submitted_vlm_review: Record<string, unknown> | null;
  comparison: Record<string, unknown> | null;
}

export async function loadAttempt(
  setId: string,
  lessonId: string,
  userId: string,
  runNo: number,
): Promise<TutorialAttemptRow | null> {
  const { data, error } = await supabaseAdmin
    .from('labeling_tutorial_attempts')
    .select('id, lesson_id, run_no, stage, submitted_gt, submitted_vlm_review, comparison')
    .eq('tutorial_set_id', setId)
    .eq('lesson_id', lessonId)
    .eq('user_id', userId)
    .eq('run_no', runNo)
    .limit(1);
  if (error) throw new Error(error.message);
  return ((data ?? [])[0] as TutorialAttemptRow | undefined) ?? null;
}

// 현재 run 의 lesson_id → stage 맵. overview·순서 강제에 사용.
export async function loadRunStages(
  setId: string,
  userId: string,
  runNo: number,
): Promise<Map<string, string>> {
  const { data, error } = await supabaseAdmin
    .from('labeling_tutorial_attempts')
    .select('lesson_id, stage')
    .eq('tutorial_set_id', setId)
    .eq('user_id', userId)
    .eq('run_no', runNo);
  if (error) throw new Error(error.message);
  return new Map((data ?? []).map((r) => [r.lesson_id as string, r.stage as string]));
}

// lesson.clip_id 의 재생용 메타(민감 필드 최소). tutorial 라우트 공용.
export async function loadLessonClip(clipId: string): Promise<{
  id: string;
  duration_sec: number | null;
  started_at: string | null;
  r2_key: string | null;
  thumbnail_r2_key: string | null;
} | null> {
  const { data, error } = await supabaseAdmin
    .from('camera_clips')
    .select('id, duration_sec, started_at, r2_key, thumbnail_r2_key')
    .eq('id', clipId)
    .limit(1);
  if (error) throw new Error(error.message);
  return (data ?? [])[0] ?? null;
}
