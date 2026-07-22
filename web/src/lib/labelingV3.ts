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
  session: MotionLabelingSession | null;
  // GT 잠금 뒤에만 존재하는 선택 필드. 잠금 전에는 키 자체가 없어야 한다(blind 계약).
  prediction?: Record<string, unknown> | null;
}
