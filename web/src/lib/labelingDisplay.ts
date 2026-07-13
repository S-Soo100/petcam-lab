// 라벨링 공통 표시 계층(설계 §7).
//
// 영문 enum·기술 용어·JSON 이 각 컴포넌트에 흩어지지 않도록 "화면에 보이는 한국어"를
// 한 곳에서 만든다. 저장 enum·API payload 는 절대 이 문자열로 바꾸지 않는다 — UI 만
// 여기 formatter 를 쓴다(설계 §7 마지막 문단).
//
// 원칙:
// - 라벨러 화면에는 GT/Blind GT/VLM/wheel/target/enrichment/action 같은 내부 용어를 노출하지 않는다.
// - raw 값(moving, wheel_interaction, { action, start_sec } …)은 그대로 렌더하지 않는다.
// - 숫자 시간은 소수점 첫째 자리까지만 보여준다(설계 §5.2).

import type {
  ContextTag,
  HighlightRecommendation,
  HumanConfidence,
  InteractionType,
  ObservedAction,
  PrimaryAction,
  Target,
  Visibility,
  VlmErrorTag,
  VlmVerdict,
  EnrichmentObject,
  ActionSegment,
} from './labelingV2';

// ── 대표 행동 ─────────────────────────────────────────────────────
// 저장 enum hand_feeding 은 유지하고 화면 라벨만 '사람이 직접 먹임'으로 바꾼다(설계 §5.1).
export const ACTION_LABELS: Record<PrimaryAction, string> = {
  eating_paste: '페이스트 먹기',
  drinking: '물 마시기',
  moving: '일반 이동',
  unknown: '판단 불가',
  eating_prey: '먹이 사냥/섭취',
  defecating: '배변',
  shedding: '탈피',
  basking: '휴식/바스킹',
  unseen: '안 보임',
  hand_feeding: '사람이 직접 먹임',
};

// ── 세부 동작 ─────────────────────────────────────────────────────
export const OBSERVED_LABELS: Record<ObservedAction, string> = {
  moving: '위치 이동',
  static: '정지/휴식',
  licking: '핥기',
  prey_capture: '먹이 포획',
  defecating: '배변 동작',
  shed_removal: '허물 벗기',
  wheel_interaction: '쳇바퀴 상호작용',
  object_interaction: '사물 상호작용',
};

// ── 대표 행동 대상 ────────────────────────────────────────────────
export const TARGET_LABELS: Record<Target, string> = {
  water: '물',
  water_bowl: '물그릇',
  food_bowl: '먹이그릇',
  paste: '페이스트',
  prey: '먹이',
  glass: '유리/벽',
  floor: '바닥',
  hand: '손',
  tool: '도구',
  object: '사물',
  none: '대상 없음',
  uncertain: '불확실',
};

// ── 촬영 환경 ─────────────────────────────────────────────────────
export const CONTEXT_LABELS: Record<ContextTag, string> = {
  ir: '야간 IR',
  glare: '반사광',
  occlusion: '가림',
  distant: '멀리 있음',
  blur: '흐림',
  overexposure: '과노출',
  edge: '화면 가장자리',
  human: '사람 등장',
  shadow: '그림자',
  camera_motion: '카메라 흔들림',
  empty_scene: '빈 장면',
};

// ── 놀이 상호작용 방법 ────────────────────────────────────────────
export const INTERACTION_LABELS: Record<InteractionType, string> = {
  ride: '올라타기',
  push: '밀기',
  rotate: '회전시키기',
  chase: '쫓기',
  repeated_return: '반복해서 돌아오기',
  other: '기타',
};

// ── 놀이에 사용한 사물(enrichment) ───────────────────────────────
export const ENRICHMENT_LABELS: Record<EnrichmentObject, string> = {
  wheel: '쳇바퀴',
  toy: '장난감',
  other: '기타 사물',
  none: '없음',
  uncertain: '불확실',
};

// ── VLM 오류 원인 ─────────────────────────────────────────────────
export const ERROR_LABELS: Record<VlmErrorTag, string> = {
  action_confusion: '행동 혼동',
  target_confusion: '대상 혼동',
  gecko_missed: '게코 놓침',
  morph_confusion: '신체/허물 혼동',
  ir_or_glare: 'IR·반사 오인',
  timing_error: '구간 오류',
  insufficient_evidence: '근거 부족',
  multi_action_missed: '복수 행동 누락',
};

// ── 가시성 ────────────────────────────────────────────────────────
export const VISIBILITY_LABELS: Record<Visibility, string> = {
  visible: '잘 보임',
  partial: '일부 보임',
  absent: '안 보임',
  uncertain: '불확실',
};

// ── 사람 판단 확실도(설계 §5.4) ──────────────────────────────────
export const CONFIDENCE_LABELS: Record<HumanConfidence, string> = {
  certain: '확실함',
  likely: '아마 맞음',
  uncertain: '잘 모르겠음',
  unjudgeable: '영상만으로 판단 불가',
};

// ── 하이라이트 여부(설계 §6.2) ───────────────────────────────────
export const HIGHLIGHT_LABELS: Record<HighlightRecommendation, string> = {
  exclude: '제외',
  uncertain: '애매',
  include: '포함',
};

// ── AI 판정 비교(설계 §4.4) ──────────────────────────────────────
// 사람 판정 대비 AI 대표 행동이 같은지를 라벨러 언어로 표현한다.
export const VERDICT_LABELS: Record<VlmVerdict, string> = {
  correct: '같음',
  partially_correct: '일부만 맞음',
  incorrect: '다름',
  unjudgeable: '비교하기 어려움',
};

export const VERDICT_HELP: Record<VlmVerdict, string> = {
  correct: 'AI의 대표 행동이 사람 판정과 같음',
  partially_correct: '완전히 같지는 않지만 행동의 일부 의미는 맞음',
  incorrect: 'AI가 다른 행동으로 판단함',
  unjudgeable: '영상이나 AI 판정이 불명확해 비교하기 어려움',
};

// 대표 행동별 한 줄 도움말(설계 §5.1).
export const PRIMARY_HELP: Partial<Record<PrimaryAction, string>> = {
  moving: '위치 이동·등반·자세 변경. 특별한 의미 행동이 없으면 일반 이동이야.',
  drinking: '몸을 고정하고 머리를 반복해서 핥는 장면. 물이 직접 안 보여도 이 패턴이면 물 마시기야.',
  hand_feeding: '사람이 손이나 도구로 먹이를 직접 먹이는 장면.',
  shedding: '허물이 실제로 벗겨지는 장면.',
  eating_paste: '페이스트를 핥아 먹는 장면.',
  eating_prey: '먹이(곤충 등)를 사냥하거나 삼키는 장면.',
};

// ── 대표 행동 대상의 동적 질문(설계 §5.3) ────────────────────────
// 고정 제목 대신 대표 행동에 따라 "무엇을 보고 무엇을 고르는지"를 질문으로 바꾼다.
export interface TargetPrompt {
  title: string;
  description: string;
}

const TARGET_PROMPT_DRINKING: TargetPrompt = {
  title: '무엇을 핥거나 마셨나?',
  description:
    '게코의 입이 실제로 닿은 대상을 골라. 물이 직접 안 보여도 접촉한 표면을 근거로 판단해.',
};
const TARGET_PROMPT_HAND_FEEDING: TargetPrompt = {
  title: '무엇으로 직접 먹였나?',
  description: '손을 사용해 직접 먹였는지, 도구를 사용해 먹였는지 골라.',
};
const TARGET_PROMPT_DEFAULT: TargetPrompt = {
  title: '이 행동은 무엇을 향했나?',
  description: '게코가 대표 행동을 하면서 직접 닿거나 향한 대상을 골라.',
};

// 세 대표 행동 모두에 붙는 공통 보조 설명(§5.3). 쳇바퀴/장난감은 대상이 아니라 놀이 근거.
export const TARGET_PROMPT_COMMON_NOTE =
  '쳇바퀴나 장난감을 사용한 행동은 아래 `놀이 행동 근거`에 기록해.';

export function targetPromptFor(primaryAction: PrimaryAction): TargetPrompt {
  if (primaryAction === 'drinking') return TARGET_PROMPT_DRINKING;
  if (primaryAction === 'hand_feeding') return TARGET_PROMPT_HAND_FEEDING;
  return TARGET_PROMPT_DEFAULT;
}

// ── 숫자 시간 포맷(설계 §5.2·§7) ─────────────────────────────────
// 화면·해설의 시간은 소수점 첫째 자리까지만. 서버 저장 정밀도는 건드리지 않는다.
// 예) 31.7999 → '31.8', 0 → '0.0'.
export function formatSeconds(sec: number): string {
  if (!Number.isFinite(sec)) return '0.0';
  return (Math.round(sec * 10) / 10).toFixed(1);
}

// segment 를 사람이 읽는 문장으로(설계 §4.5·§7). 예) '핥기 13.0초~31.8초'.
export function describeSegment(segment: ActionSegment): string {
  return `${OBSERVED_LABELS[segment.action] ?? segment.action} ${formatSeconds(
    segment.start_sec,
  )}초~${formatSeconds(segment.end_sec)}초`;
}

// ── 사람용 값 표시(설계 §4.5·§7) ─────────────────────────────────
// 배열은 한국어 항목을 쉼표로 잇고, none/null/빈값은 '없음'으로 보여준다.
// raw 값은 절대 그대로 렌더하지 않고 label map 을 통과시킨다.
function labelWith(map: Record<string, string>, value: string): string {
  return map[value] ?? value;
}

function formatList(values: readonly string[], map: Record<string, string>): string {
  if (!values || values.length === 0) return '없음';
  return values.map((v) => labelWith(map, v)).join(', ');
}

// 튜토리얼 피드백 dimension 값 → 한국어 문장(설계 §4.5). key 별로 알맞은 label map/formatter 를 고른다.
export function formatDimensionValue(key: string, value: unknown): string {
  if (value === null || value === undefined || value === '') return '없음';
  if (key === 'segments' && Array.isArray(value)) {
    return value.length
      ? (value as ActionSegment[]).map((s) => describeSegment(s)).join(', ')
      : '없음';
  }
  switch (key) {
    case 'visibility':
      return labelWith(VISIBILITY_LABELS, String(value));
    case 'primary_action':
      return labelWith(ACTION_LABELS, String(value));
    case 'target':
      return labelWith(TARGET_LABELS, String(value));
    case 'highlight_recommendation':
      return labelWith(HIGHLIGHT_LABELS, String(value));
    case 'enrichment_object':
      return labelWith(ENRICHMENT_LABELS, String(value));
    case 'human_confidence':
      return labelWith(CONFIDENCE_LABELS, String(value));
    case 'vlm_verdict':
      return labelWith(VERDICT_LABELS, String(value));
    case 'observed_actions':
      return formatList(value as string[], OBSERVED_LABELS);
    case 'interaction_types':
      return formatList(value as string[], INTERACTION_LABELS);
    case 'context_tags':
      return formatList(value as string[], CONTEXT_LABELS);
    case 'vlm_error_tags':
      return formatList(value as string[], ERROR_LABELS);
    case 'note':
      return String(value);
    default:
      // 알 수 없는 dimension 도 raw JSON 을 노출하지 않는다.
      if (Array.isArray(value)) return value.length ? value.map((v) => String(v)).join(', ') : '없음';
      if (typeof value === 'object') return '없음';
      return String(value);
  }
}

// 튜토리얼 피드백에서 dimension 을 사람이 읽는 제목으로(설계 §4.5).
export const DIMENSION_LABELS: Record<string, string> = {
  visibility: '게코가 보이는지',
  primary_action: '대표 행동',
  target: '행동 대상',
  highlight_recommendation: '하이라이트 여부',
  enrichment_object: '놀이에 사용한 사물',
  observed_actions: '실제 동작',
  interaction_types: '놀이에 사용한 방법',
  segments: '동작과 시간',
  vlm_verdict: 'AI 판정 비교',
  vlm_error_tags: 'AI 오류 원인',
  human_confidence: '판단 확실도',
  context_tags: '촬영 환경',
  note: '메모',
};

export function dimensionLabel(key: string): string {
  return DIMENSION_LABELS[key] ?? key;
}
