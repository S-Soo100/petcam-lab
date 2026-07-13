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

// 하이라이트 판정(설계 §6). activity_intensity(움직임 세기)와 다른 축 —
// "고객에게 보여줄 장면인가"를 뜻한다. 별도 필드로 저장해 legacy 값과 섞지 않는다.
export const HIGHLIGHT_RECOMMENDATIONS = ['exclude', 'uncertain', 'include'] as const;

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

export function formatClipCapturedAt(
  startedAt: string,
  durationSec: number | null,
): string {
  const parts = partsByType(
    new Intl.DateTimeFormat('ko-KR', {
      timeZone: 'Asia/Seoul',
      year: 'numeric',
      month: 'numeric',
      day: 'numeric',
      weekday: 'short',
      hour: 'numeric',
      minute: '2-digit',
      second: '2-digit',
      hour12: true,
    }).formatToParts(new Date(startedAt)),
  );
  const dayPeriod = parts.dayPeriod === 'AM' ? '오전' : parts.dayPeriod === 'PM' ? '오후' : parts.dayPeriod;
  const captured = `${parts.year}년 ${Number(parts.month)}월 ${Number(parts.day)}일 (${parts.weekday}) ${dayPeriod} ${Number(parts.hour)}:${parts.minute}:${parts.second}`;
  const duration = Number.isFinite(durationSec)
    ? ` · ${Math.round(durationSec as number)}초`
    : '';
  return `촬영 · ${captured}${duration}`;
}

export function clipDownloadFilename(startedAt: string, clipId: string): string {
  const parts = partsByType(
    new Intl.DateTimeFormat('en-CA', {
      timeZone: 'Asia/Seoul',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hourCycle: 'h23',
    }).formatToParts(new Date(startedAt)),
  );
  return `petcam_${parts.year}-${parts.month}-${parts.day}_${parts.hour}${parts.minute}${parts.second}_${clipId.slice(0, 8)}.mp4`;
}

function partsByType(parts: Intl.DateTimeFormatPart[]): Record<string, string> {
  return Object.fromEntries(
    parts.filter((part) => part.type !== 'literal').map((part) => [part.type, part.value]),
  );
}

export type PrimaryAction = (typeof PRIMARY_ACTIONS)[number];
export type ObservedAction = (typeof OBSERVED_ACTIONS)[number];
export type Target = (typeof TARGETS)[number];
export type ContextTag = (typeof CONTEXT_TAGS)[number];
export type InteractionType = (typeof INTERACTION_TYPES)[number];
export type VlmErrorTag = (typeof VLM_ERROR_TAGS)[number];
export type Visibility = 'visible' | 'partial' | 'absent' | 'uncertain';
export type HumanConfidence = 'certain' | 'likely' | 'uncertain' | 'unjudgeable';
export type ActivityIntensity = 'low' | 'medium' | 'high';
export type HighlightRecommendation = (typeof HIGHLIGHT_RECOMMENDATIONS)[number];
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
  // legacy read 전용(설계 §6.3): 과거 GT 는 low|medium|high, 신규 GT 는 null 로 저장한다.
  activity_intensity: ActivityIntensity | null;
  // 신규 하이라이트 판정(§6.2). non-absent GT 는 라벨러가 반드시 직접 고른다.
  highlight_recommendation: HighlightRecommendation;
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

// ── GT 입력 검증 계약 (설계 §6) ────────────────────────────────────
// client(폼 인라인 오류)와 server(400)가 하나의 순수 규칙 함수를 공유한다.
// 라벨러가 실제로 고칠 수 있는 "의미 규칙"은 issue 로 모으고, malformed payload
// (enum/타입 깨짐 — 정상 클라이언트에선 안 나옴)는 validateGroundTruth 가 plain
// Error 로 먼저 막는다.

export type GroundTruthField =
  | 'visibility'
  | 'primary_action'
  | 'observed_actions'
  | 'segments'
  | 'target'
  | 'human_confidence'
  | 'context_tags'
  | 'highlight_recommendation'
  | 'enrichment_object'
  | 'interaction_types';

// 폼이 관리하는 draft — 값은 비-null 계약을 유지하되(설계 §6.1) 어떤 필드를
// 라벨러가 "직접" 선택했는지를 따로 추적해 기본값 프리셀렉트를 없앤다.
export interface GroundTruthDraftState {
  value: GroundTruthInput;
  explicitlySelected: Set<GroundTruthField>;
}

export interface GroundTruthValidationIssue {
  field: GroundTruthField;
  code: string;
  message: string;
}

// 첫 오류로 스크롤/포커스할 때의 우선순위 — 폼 위→아래 순서.
export const GROUND_TRUTH_FIELD_ORDER: readonly GroundTruthField[] = [
  'visibility',
  'primary_action',
  'observed_actions',
  'segments',
  'target',
  'human_confidence',
  'highlight_recommendation',
  'context_tags',
  'enrichment_object',
  'interaction_types',
];

// drinking 대표 행동의 허용 대상(설계 §6.2 규칙 7). wheel 은 target 이 아니다.
export const DRINKING_TARGETS: readonly Target[] = [
  'water',
  'water_bowl',
  'glass',
  'floor',
  'uncertain',
];
// 사람 급여 대표 행동의 허용 대상(설계 §6.2 규칙 8).
export const HAND_FEEDING_TARGETS: readonly Target[] = ['hand', 'tool'];

// 대표 행동별 허용 대상(설계 §4.2·§5.5). drinking/hand_feeding 은 좁히고 나머지는 전체.
// wheel 은 어떤 대표 행동의 target 도 아니다(enrichment_object 로 따로 받는다).
export function allowedTargetsFor(primaryAction: PrimaryAction): readonly Target[] {
  if (primaryAction === 'drinking') return DRINKING_TARGETS;
  if (primaryAction === 'hand_feeding') return HAND_FEEDING_TARGETS;
  return TARGETS;
}

export class GroundTruthValidationError extends Error {
  readonly issues: GroundTruthValidationIssue[];
  constructor(issues: GroundTruthValidationIssue[]) {
    super(issues[0]?.message ?? 'GT 입력이 유효하지 않아.');
    this.name = 'GroundTruthValidationError';
    this.issues = issues;
  }
}

// 폼 위→아래 순서로 정렬(첫 오류 스크롤용). 같은 필드 여러 issue 는 push 순서 유지.
function sortGroundTruthIssues(
  issues: GroundTruthValidationIssue[],
): GroundTruthValidationIssue[] {
  return issues
    .map((issue, index) => ({ issue, index }))
    .sort((a, b) => {
      const rank =
        GROUND_TRUTH_FIELD_ORDER.indexOf(a.issue.field) -
        GROUND_TRUTH_FIELD_ORDER.indexOf(b.issue.field);
      return rank !== 0 ? rank : a.index - b.index;
    })
    .map((entry) => entry.issue);
}

export function firstIssueField(
  issues: readonly GroundTruthValidationIssue[],
): GroundTruthField | null {
  return issues.length > 0 ? issues[0].field : null;
}

// owner 보정 확인 단계에서 "무엇이 바뀌었나"를 보여주기 위한 순수 diff(설계 §7.4).
// 배열/객체는 JSON 문자열로 비교한다(segments 순서·context 순서 차이도 변경으로 본다).
export function changedGroundTruthFields(
  before: GroundTruthInput,
  after: GroundTruthInput,
): (keyof GroundTruthInput)[] {
  const keys: (keyof GroundTruthInput)[] = [
    'visibility', 'primary_action', 'observed_actions', 'segments', 'target',
    'human_confidence', 'context_tags', 'activity_intensity', 'highlight_recommendation',
    'enrichment_object', 'interaction_types', 'note',
  ];
  return keys.filter((key) => JSON.stringify(before[key]) !== JSON.stringify(after[key]));
}

// client/server 공유 순수 규칙(설계 §6.2). server 는 explicitlySelected 를 넘기지
// 않으므로 "직접 선택"(규칙 1)은 client 전용이고, 나머지는 값 기반으로 동일하게 강제된다.
export function collectGroundTruthIssues(
  input: GroundTruthInput,
  clipDurationSec: number,
  explicitlySelected?: ReadonlySet<GroundTruthField>,
): GroundTruthValidationIssue[] {
  const issues: GroundTruthValidationIssue[] = [];
  const push = (field: GroundTruthField, code: string, message: string) =>
    issues.push({ field, code, message });

  // 1. 가시성·대표 행동은 라벨러가 직접 선택해야 한다(client 전용 UX 계약).
  if (explicitlySelected) {
    if (!explicitlySelected.has('visibility')) {
      push('visibility', 'visibility_not_selected', '게코가 보이는지 먼저 골라줘.');
    }
    if (!explicitlySelected.has('primary_action')) {
      push('primary_action', 'primary_action_not_selected', '대표 행동을 직접 골라줘.');
    }
  }

  // 9. playing 은 직접 대표 행동으로 저장할 수 없다(타입상 없지만 방어).
  if (String(input.primary_action) === 'playing') {
    push(
      'primary_action',
      'playing_not_primary',
      'playing은 직접 라벨이 아니라 interaction evidence에서 파생해.',
    );
  }

  if (input.visibility === 'absent') {
    // 2. absent → unseen 정규화 계약. 나머지 값 기반 규칙은 의미가 없으므로 여기서 종료.
    if (input.primary_action !== 'unseen') {
      push('primary_action', 'absent_requires_unseen', '게코가 안 보임이면 대표 행동은 unseen이어야 해.');
    }
    if (input.observed_actions.length > 0) {
      push('observed_actions', 'absent_no_observed', '안 보임이면 세부 행동을 비워야 해.');
    }
    if (input.segments.length > 0) {
      push('segments', 'absent_no_segments', '안 보임이면 행동 구간을 비워야 해.');
    }
    if (input.target !== 'none') {
      push('target', 'absent_target_none', '안 보임이면 대표 행동 대상은 대상 없음이어야 해.');
    }
    if (input.enrichment_object !== 'none') {
      push('enrichment_object', 'absent_enrichment_none', '안 보임이면 enrichment 근거를 비워야 해.');
    }
    if (input.interaction_types.length > 0) {
      push('interaction_types', 'absent_no_interaction', '안 보임이면 상호작용 유형을 비워야 해.');
    }
    // 2''. absent → highlight 는 '제외'로 정규화(설계 §6.3). 화면에선 숨기고 폼이 자동 설정한다.
    if (input.highlight_recommendation !== 'exclude') {
      push('highlight_recommendation', 'absent_highlight_exclude', '안 보임이면 하이라이트 여부는 제외여야 해.');
    }
    return sortGroundTruthIssues(issues);
  }

  // 2'. unseen 은 absent 에서만.
  if (input.primary_action === 'unseen') {
    push('primary_action', 'unseen_requires_absent', '대표 행동 unseen은 게코가 안 보임일 때만 쓸 수 있어.');
  }

  // 2b. (non-absent) 하이라이트 여부는 라벨러가 직접 골라야 한다(client 전용 UX 계약, §6.3).
  //     server 는 explicitlySelected 를 넘기지 않으므로 값 enum 검증만(validateGroundTruth).
  if (explicitlySelected && !explicitlySelected.has('highlight_recommendation')) {
    push('highlight_recommendation', 'highlight_not_selected', '하이라이트 여부를 골라줘.');
  }

  // 3. visible/partial/uncertain 은 관찰 행동이 하나 이상.
  if (input.observed_actions.length === 0) {
    push('observed_actions', 'observed_required', '게코가 보이면 세부 행동을 하나 이상 골라야 해.');
  }

  // 4. 모든 observed action 에는 정확히 하나의 segment(누락·중복·orphan 금지).
  let missingSegment = false;
  let duplicateSegment = false;
  for (const action of input.observed_actions) {
    const count = input.segments.filter((segment) => segment.action === action).length;
    if (count === 0) missingSegment = true;
    if (count > 1) duplicateSegment = true;
  }
  if (missingSegment) {
    push('segments', 'segment_missing', '선택한 세부 행동마다 행동 구간이 하나씩 필요해.');
  }
  if (duplicateSegment) {
    push('segments', 'segment_duplicate', '같은 세부 행동의 구간은 하나만 만들 수 있어.');
  }
  if (input.segments.some((segment) => !input.observed_actions.includes(segment.action))) {
    push('segments', 'segment_orphan', '행동 구간은 선택한 세부 행동에만 만들 수 있어.');
  }
  // 5. segment 는 0 <= start < end <= duration.
  if (
    input.segments.some(
      (segment) =>
        !(
          segment.start_sec >= 0 &&
          segment.start_sec < segment.end_sec &&
          segment.end_sec <= clipDurationSec
        ),
    )
  ) {
    push('segments', 'segment_range', '행동 구간은 영상 길이 안에서 시작보다 끝이 커야 해.');
  }

  // 6. wheel/object interaction 에는 object 와 interaction type 이 모두 필요.
  const hasInteraction = input.observed_actions.some(
    (action) => action === 'wheel_interaction' || action === 'object_interaction',
  );
  if (hasInteraction) {
    if (input.enrichment_object === 'none') {
      push('enrichment_object', 'enrichment_object_required', '상호작용 근거에는 대상(쳇바퀴 등)이 필요해.');
    }
    if (input.interaction_types.length === 0) {
      push('interaction_types', 'interaction_type_required', '쳇바퀴 상호작용 방식을 하나 이상 골라줘.');
    }
  }

  // 7. drinking target 화이트리스트.
  if (
    input.primary_action === 'drinking' &&
    !DRINKING_TARGETS.includes(input.target)
  ) {
    push('target', 'drinking_target_invalid', '물 마시기 대상은 물·물그릇·유리/벽·바닥·불확실 중 하나여야 해.');
  }

  // 8. hand feeding 3 근거: licking/prey_capture + target hand/tool + context human.
  if (input.primary_action === 'hand_feeding') {
    if (!input.observed_actions.some((action) => action === 'licking' || action === 'prey_capture')) {
      push('observed_actions', 'hand_feeding_action', '사람 급여는 핥기 또는 먹이 포획 근거가 필요해.');
    }
    if (!HAND_FEEDING_TARGETS.includes(input.target)) {
      push('target', 'hand_feeding_target', '사람 급여 대표 행동 대상은 손 또는 도구여야 해.');
    }
    if (!input.context_tags.includes('human')) {
      push('context_tags', 'hand_feeding_context', '사람 급여는 사람 등장(human) 태그가 필요해.');
    }
  }

  return sortGroundTruthIssues(issues);
}

export function validateGroundTruth(
  value: unknown,
  clipDurationSec: number,
): GroundTruthInput {
  if (!isRecord(value)) throw new Error('GT 입력 형식이 잘못됐어.');

  const input = value as unknown as GroundTruthInput;
  // 구조/enum 가드 — malformed payload 만 여기서 plain Error 로 막는다.
  requireOne(input.visibility, VISIBILITIES, '가시성');
  // playing 은 enum 밖이지만 collectGroundTruthIssues 가 friendly issue 로 처리한다.
  if (String(input.primary_action) !== 'playing') {
    requireOne(input.primary_action, PRIMARY_ACTIONS, '대표 행동');
  }
  requireArray(input.observed_actions, OBSERVED_ACTIONS, '세부 행동');
  requireOne(input.target, TARGETS, '대표 행동 대상');
  requireOne(input.human_confidence, HUMAN_CONFIDENCES, '사람 확신도');
  requireArray(input.context_tags, CONTEXT_TAGS, '환경 태그');
  // activity_intensity 는 legacy read 전용(§6.3): null 허용, 값이 있으면 enum 검증.
  if (input.activity_intensity !== null) {
    requireOne(input.activity_intensity, ACTIVITY_INTENSITIES, '활동 강도');
  }
  requireOne(input.highlight_recommendation, HIGHLIGHT_RECOMMENDATIONS, '하이라이트 여부');
  requireOne(input.enrichment_object, ENRICHMENT_OBJECTS, 'enrichment object');
  requireArray(input.interaction_types, INTERACTION_TYPES, '상호작용 유형');
  if (!Array.isArray(input.segments)) throw new Error('행동 구간 형식이 잘못됐어.');
  for (const segment of input.segments) {
    if (!isRecord(segment)) throw new Error('행동 구간 형식이 잘못됐어.');
    requireOne(segment.action, OBSERVED_ACTIONS, '구간 행동');
    if (!Number.isFinite(segment.start_sec) || !Number.isFinite(segment.end_sec)) {
      throw new Error('행동 구간 형식이 잘못됐어.');
    }
  }
  if (input.note !== null && typeof input.note !== 'string') {
    throw new Error('메모 형식이 잘못됐어.');
  }
  if (input.note && input.note.length > 2000) throw new Error('메모는 2000자 이하여야 해.');

  // 의미 규칙(설계 §6.2) — server 는 값 기반만(explicitlySelected 없음).
  const issues = collectGroundTruthIssues(input, clipDurationSec);
  if (issues.length > 0) throw new GroundTruthValidationError(issues);
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
