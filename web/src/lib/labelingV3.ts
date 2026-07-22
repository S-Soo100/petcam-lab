// motion_clips 네이티브 운영 라벨링 v3 — 공개 타입 + 순수 규칙.
//
// 설계 정본: docs/superpowers/specs/2026-07-22-motion-clips-native-labeling-design.md
// 이 파일은 client/server 가 공유하는 순수 계약만 둔다(DB·server-only 의존 없음).
// GroundTruthInput / VlmVerdict / VlmErrorTag 는 v2 검증 계약을 그대로 재사용한다(변경 금지).

import type { GroundTruthInput, VlmErrorTag, VlmVerdict } from './labelingV2';

// ── 상태/스테이지 ─────────────────────────────────────────────────
// legacy triage 의 label|skip|quarantine 과 의미가 다르다. 운영 v3 는 owner_decision
// 4상태로만 접힌다: row 없음/미결정=unreviewed, 그리고 label|hold|skip.
export type MotionLabelingState = 'unreviewed' | 'label' | 'hold' | 'skip';
export type MotionSessionStage = 'draft' | 'gt_locked' | 'completed';
export type MotionCompletionReason = 'vlm_reviewed' | 'no_prediction';

const MOTION_STATES: readonly MotionLabelingState[] = [
  'unreviewed',
  'label',
  'hold',
  'skip',
];

// DB/RPC state 문자열 → 타입 안전 상태. null/undefined=unreviewed, 미지 값은 throw.
// client·server 가 같은 파서를 쓰므로 legacy 값(quarantine)이 섞이면 즉시 드러난다.
export function parseMotionState(
  raw: string | null | undefined,
): MotionLabelingState {
  if (raw === null || raw === undefined) return 'unreviewed';
  if ((MOTION_STATES as readonly string[]).includes(raw)) {
    return raw as MotionLabelingState;
  }
  throw new Error('invalid_motion_state');
}

// ── GT 쓰기 가능 상태 규칙 (설계 §4·§5.1) ─────────────────────────
// owner 가 hold/skip 으로 접은 clip 은 사람 판정(GT)을 저장할 수 없다. GT 잠금 RPC 가
// label 이 아닌 상태를 label 로 원자 전환하기 때문에, 그대로 두면 결정이 조용히 뒤집힌다.
// UI 는 이 규칙으로 GT 폼을 잠그고, DB guard(PT424)가 최종 경합 경계를 강제한다.
export function canWriteMotionGt(state: MotionLabelingState): boolean {
  return state === 'unreviewed' || state === 'label';
}

// owner 팀 큐 분류 결정. label|hold|skip 은 상태 전환, reset 은 unreviewed 로 초기화(설계 §5.3).
// (client API 와 undo 규칙이 공유하므로 순수 계약 파일에 둔다. labelingV3Api 가 re-export.)
export type MotionDecision = 'label' | 'hold' | 'skip' | 'reset';

// 분류 성공 결과 — 직전/새 상태와 새 updated_at 을 보관해 결정 취소(undo)와 결과 안내에 쓴다(설계 §7.1).
export interface MotionDecisionChange {
  previous: MotionLabelingState;
  next: MotionLabelingState;
  updatedAt: string;
}

// 결정 취소가 호출할 decision. 직전이 unreviewed 면 reset(분류 제거), 아니면 그 상태로 되돌린다(설계 §7.2).
// 강제 탭 이동(옛 motionDecisionListPath)을 없애고 연속 검수 흐름의 undo 로 대체했다.
export function motionUndoDecision(previous: MotionLabelingState): MotionDecision {
  return previous === 'unreviewed' ? 'reset' : previous;
}

// ── 큐 ────────────────────────────────────────────────────────────
export interface MotionQueueItem {
  id: string;
  camera_id: string;
  camera_name: string;
  started_at: string;
  duration_sec: number;
  media_ready: boolean;
  state: MotionLabelingState;
  session_stage: MotionSessionStage | null;
}

export interface MotionQueueResponse {
  items: MotionQueueItem[];
  next_cursor: string | null;
  has_more: boolean;
}

export interface MotionCameraOption {
  id: string;
  name: string;
}

// owner 전용 "현재 필터의 다음 미분류 영상" 조회 응답(설계 §6). 다음이 없으면 null(검수 완료).
export interface MotionNextResponse {
  next_clip_id: string | null;
}

// ── 상세/세션 ─────────────────────────────────────────────────────
// GT 잠금 전에는 prediction/verdict/evidence 를 담지 않는다(설계 §9). prediction 은
// session.stage 가 gt_locked|completed 일 때만 detail 에 선택적으로 붙는다.
export interface MotionLabelingSession {
  stage: MotionSessionStage;
  initial_gt: GroundTruthInput | null;
  current_gt: GroundTruthInput | null;
  vlm_verdict: VlmVerdict | null;
  vlm_error_tags: VlmErrorTag[];
  vlm_review_note: string | null;
  completion_reason: MotionCompletionReason | null;
  gt_locked_at: string | null;
  completed_at: string | null;
}

export interface MotionClipDetail {
  id: string;
  camera_id: string;
  camera_name: string;
  started_at: string;
  duration_sec: number;
  media_ready: boolean;
  state: MotionLabelingState;
  // triage row 의 updated_at(없으면 null). owner 결정 optimistic concurrency 기준값.
  state_updated_at: string | null;
  session: MotionLabelingSession | null;
  // GT 잠금 뒤에만 존재하는 선택 필드. 잠금 전에는 키 자체가 없어야 한다(blind 계약).
  prediction?: Record<string, unknown> | null;
}

// ── 상세 화면 phase 상태기계 (설계 §5.2) ──────────────────────────
// 세션/미디어 상태로 화면 단계를 정한다. client/UI 가 공유하는 순수 규칙.
//   gt: blind GT 작성 · review: GT 잠금 후 VLM 검수 · complete: 완료(owner 보정 가능)
//   media_blocked: 세션 없음 + 재생 불가(GT 저장 금지)
export type MotionDetailPhase = 'gt' | 'review' | 'complete' | 'media_blocked';

export function decideMotionDetailPhase(input: {
  session: { stage: MotionSessionStage } | null;
  media_ready?: boolean;
}): MotionDetailPhase {
  if (input.session) {
    if (input.session.stage === 'completed') return 'complete';
    if (input.session.stage === 'gt_locked') return 'review';
    // draft 세션은 v3 에선 만들지 않지만, 방어적으로 GT 작성 단계로 본다.
  }
  if (input.media_ready === false) return 'media_blocked';
  return 'gt';
}

// ── /labeling 기본 소스 결정 (Task 9 전환 게이트) ─────────────────
// LABELING_QUEUE_SOURCE env 로 운영 라벨링을 legacy(camera_clips) ↔ motion(v3) 전환한다.
// 기본은 항상 legacy — production 전환은 이 handoff 밖(명시 승인 후 env 로만).
export type LabelingQueueSource = 'legacy' | 'motion';

export function resolveLabelingQueueSource(
  raw: string | null | undefined,
): LabelingQueueSource {
  return raw === 'motion' ? 'motion' : 'legacy';
}
