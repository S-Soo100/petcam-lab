export const PRIMARY_ACTIONS = [
  'eating_paste',
  'drinking',
  'moving',
  'unknown',
  'eating_prey',
  'defecating',
  'shedding',
  'basking',
  'unseen',
  'hand_feeding',
] as const;

export const OBSERVED_ACTIONS = [
  'moving',
  'static',
  'licking',
  'prey_capture',
  'defecating',
  'shed_removal',
  'wheel_interaction',
  'object_interaction',
] as const;

export const TARGETS = [
  'water',
  'water_bowl',
  'food_bowl',
  'paste',
  'prey',
  'glass',
  'floor',
  'hand',
  'tool',
  'object',
  'none',
  'uncertain',
] as const;

export const CONTEXT_TAGS = [
  'ir',
  'glare',
  'occlusion',
  'distant',
  'blur',
  'overexposure',
  'edge',
  'human',
  'shadow',
  'camera_motion',
  'empty_scene',
] as const;

export const INTERACTION_TYPES = [
  'ride',
  'push',
  'rotate',
  'chase',
  'repeated_return',
  'other',
] as const;

export const VLM_ERROR_TAGS = [
  'action_confusion',
  'target_confusion',
  'gecko_missed',
  'morph_confusion',
  'ir_or_glare',
  'timing_error',
  'insufficient_evidence',
  'multi_action_missed',
] as const;

// 실제 production camera_clips 컬럼만 사용한다. 오래된 타입의 ended_at을 넣으면
// PostgREST가 전체 blind queue 요청을 400으로 거부한다.
export const BLIND_QUEUE_CLIP_COLUMNS =
  'id,user_id,camera_id,pet_id,started_at,duration_sec,has_motion,r2_key,thumbnail_r2_key';

export type PrimaryAction = (typeof PRIMARY_ACTIONS)[number];
export type ObservedAction = (typeof OBSERVED_ACTIONS)[number];
export type Target = (typeof TARGETS)[number];
export type ContextTag = (typeof CONTEXT_TAGS)[number];
export type InteractionType = (typeof INTERACTION_TYPES)[number];
export type VlmErrorTag = (typeof VLM_ERROR_TAGS)[number];
export type Visibility = 'visible' | 'partial' | 'absent' | 'uncertain';
export type HumanConfidence = 'certain' | 'likely' | 'uncertain' | 'unjudgeable';
export type ActivityIntensity = 'low' | 'medium' | 'high';
export type EnrichmentObject = 'wheel' | 'toy' | 'other' | 'none' | 'uncertain';
export type VlmVerdict = 'correct' | 'partially_correct' | 'incorrect' | 'unjudgeable';
export type LabelingStage = 'draft' | 'gt_locked' | 'completed';

export interface ActionSegment {
  action: ObservedAction;
  start_sec: number;
  end_sec: number;
}

export interface GroundTruthInput {
  visibility: Visibility;
  primary_action: PrimaryAction;
  observed_actions: ObservedAction[];
  segments: ActionSegment[];
  target: Target;
  human_confidence: HumanConfidence;
  context_tags: ContextTag[];
  activity_intensity: ActivityIntensity;
  enrichment_object: EnrichmentObject;
  interaction_types: InteractionType[];
  note: string | null;
}

export interface VlmReviewInput {
  verdict: VlmVerdict;
  error_tags: VlmErrorTag[];
  note: string | null;
}

export interface LabelingSession {
  id: string;
  clip_id: string;
  reviewed_by: string;
  stage: LabelingStage;
  initial_gt: GroundTruthInput | null;
  current_gt: GroundTruthInput | null;
  prediction_snapshot: Record<string, unknown> | null;
  vlm_verdict: VlmVerdict | null;
  vlm_error_tags: VlmErrorTag[];
  vlm_review_note: string | null;
  completion_reason: 'vlm_reviewed' | 'no_prediction' | null;
  gt_locked_at: string | null;
  completed_at: string | null;
}

const VISIBILITIES = ['visible', 'partial', 'absent', 'uncertain'] as const;
const HUMAN_CONFIDENCES = ['certain', 'likely', 'uncertain', 'unjudgeable'] as const;
const ACTIVITY_INTENSITIES = ['low', 'medium', 'high'] as const;
const ENRICHMENT_OBJECTS = ['wheel', 'toy', 'other', 'none', 'uncertain'] as const;
const VLM_VERDICTS = ['correct', 'partially_correct', 'incorrect', 'unjudgeable'] as const;

export function validateGroundTruth(
  value: unknown,
  clipDurationSec: number,
): GroundTruthInput {
  if (!isRecord(value)) throw new Error('GT 입력 형식이 잘못됐어.');

  const input = value as unknown as GroundTruthInput;
  requireOne(input.visibility, VISIBILITIES, '가시성');
  if (String(input.primary_action) === 'playing') {
    throw new Error('playing은 직접 라벨이 아니라 interaction evidence에서 파생해.');
  }
  requireOne(input.primary_action, PRIMARY_ACTIONS, '대표 행동');
  requireArray(input.observed_actions, OBSERVED_ACTIONS, '관찰 행동');
  requireOne(input.target, TARGETS, '행동 대상');
  requireOne(input.human_confidence, HUMAN_CONFIDENCES, '사람 확신도');
  requireArray(input.context_tags, CONTEXT_TAGS, '환경 태그');
  requireOne(input.activity_intensity, ACTIVITY_INTENSITIES, '활동 강도');
  requireOne(input.enrichment_object, ENRICHMENT_OBJECTS, 'enrichment object');
  requireArray(input.interaction_types, INTERACTION_TYPES, '상호작용 유형');

  if (input.visibility === 'absent' && input.primary_action !== 'unseen') {
    throw new Error('게코가 안 보임이면 대표 행동은 unseen이어야 해.');
  }
  if (input.visibility !== 'absent' && input.primary_action === 'unseen') {
    throw new Error('대표 행동 unseen은 게코가 안 보임일 때만 쓸 수 있어.');
  }
  if (input.visibility !== 'absent' && input.observed_actions.length === 0) {
    throw new Error('게코가 보이면 관찰 행동을 하나 이상 골라야 해.');
  }
  const hasInteraction = input.observed_actions.some(
    (action) => action === 'wheel_interaction' || action === 'object_interaction',
  );
  if (
    hasInteraction &&
    (input.enrichment_object === 'none' || input.interaction_types.length === 0)
  ) {
    throw new Error('상호작용 근거에는 object와 interaction type이 필요해.');
  }
  if (!Array.isArray(input.segments)) throw new Error('행동 구간 형식이 잘못됐어.');
  for (const segment of input.segments) {
    if (!isRecord(segment)) throw new Error('행동 구간 형식이 잘못됐어.');
    requireOne(segment.action, OBSERVED_ACTIONS, '구간 행동');
    if (
      !Number.isFinite(segment.start_sec) ||
      !Number.isFinite(segment.end_sec) ||
      segment.start_sec < 0 ||
      segment.end_sec <= segment.start_sec ||
      segment.end_sec > clipDurationSec
    ) {
      throw new Error('행동 구간은 영상 길이 안에서 시작보다 끝이 커야 해.');
    }
    if (!input.observed_actions.includes(segment.action)) {
      throw new Error('행동 구간은 선택한 관찰 행동에만 만들 수 있어.');
    }
  }
  if (
    input.visibility !== 'absent' &&
    input.observed_actions.some(
      (action) => !input.segments.some((segment) => segment.action === action),
    )
  ) {
    throw new Error('각 관찰 행동에는 영상 구간이 하나 이상 필요해.');
  }
  if (input.note !== null && typeof input.note !== 'string') {
    throw new Error('메모 형식이 잘못됐어.');
  }
  if (input.note && input.note.length > 2000) throw new Error('메모는 2000자 이하여야 해.');

  return input;
}

export function validateVlmReview(value: unknown): VlmReviewInput {
  if (!isRecord(value)) throw new Error('VLM 검수 입력 형식이 잘못됐어.');
  const input = value as unknown as VlmReviewInput;
  requireOne(input.verdict, VLM_VERDICTS, 'VLM verdict');
  requireArray(input.error_tags, VLM_ERROR_TAGS, 'VLM 오류 유형');
  if (
    (input.verdict === 'incorrect' || input.verdict === 'partially_correct') &&
    input.error_tags.length === 0
  ) {
    throw new Error('오답이나 부분정답에는 오류 유형이 필요해.');
  }
  if (input.note !== null && typeof input.note !== 'string') {
    throw new Error('VLM 검수 메모 형식이 잘못됐어.');
  }
  if (input.note && input.note.length > 2000) throw new Error('메모는 2000자 이하여야 해.');
  return input;
}

export function revealPrediction<T>(
  session: { initial_gt: unknown | null } | null,
  prediction: T,
): T | null {
  return session?.initial_gt ? prediction : null;
}

export function nextStage(
  current: LabelingStage,
  event: 'lock_gt' | 'complete_vlm_review',
): LabelingStage {
  if (current === 'draft' && event === 'lock_gt') return 'gt_locked';
  if (current === 'gt_locked' && event === 'complete_vlm_review') return 'completed';
  throw new Error(`허용되지 않은 라벨링 단계 전환이야: ${current} -> ${event}`);
}

export function thumbnailKeyForClip(clip: {
  thumbnail_r2_key: string | null;
  r2_key: string | null;
}): string {
  if (clip.thumbnail_r2_key) return clip.thumbnail_r2_key;
  if (clip.r2_key?.toLowerCase().endsWith('.mp4')) {
    return `${clip.r2_key.slice(0, -4)}.jpg`;
  }
  throw new Error('썸네일 R2 key를 만들 수 없어.');
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function requireOne<T extends string>(
  value: unknown,
  allowed: readonly T[],
  label: string,
): asserts value is T {
  if (typeof value !== 'string' || !allowed.includes(value as T)) {
    throw new Error(`${label} 값이 잘못됐어.`);
  }
}

function requireArray<T extends string>(
  value: unknown,
  allowed: readonly T[],
  label: string,
): asserts value is T[] {
  if (!Array.isArray(value) || value.some((item) => !allowed.includes(item as T))) {
    throw new Error(`${label} 값이 잘못됐어.`);
  }
}
