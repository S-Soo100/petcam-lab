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

import { isValidHighlight } from './labelingV2';
import type {
  ActivityIntensity,
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

// 라벨 map 에 없는 값(legacy·손상·미지 enum)을 일반 라벨러에게 raw 영문으로 보여주지 않는다(하드닝 §7).
export const UNKNOWN_LABEL = '확인 필요';

// ── 대표 행동 ─────────────────────────────────────────────────────
// 저장 enum hand_feeding 은 유지하고 화면 라벨만 '사람이 직접 먹임'으로 바꾼다(설계 §5.1).
// 저장 enum(eating_paste/eating_prey/basking/tool/object …)은 유지하고 화면 명칭만
// 운영 용어로 맞춘다(설계 §4.2·§5.1). basking 은 호환용 저장 키로 남기되 화면에선
// "게코가 실질적으로 움직이지 않고 쉬는 상태"를 뜻한다(설계 §4.2).
export const ACTION_LABELS: Record<PrimaryAction, string> = {
  eating_paste: '슈퍼푸드 자율급여',
  drinking: '물 마시기',
  moving: '일반 이동',
  unknown: '판단 불가',
  eating_prey: '곤충 사냥',
  defecating: '배변',
  shedding: '탈피',
  basking: '휴식',
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
  // 사람이 직접 먹일 때 쓰는 급여 도구(설계 §4.2). 사육장 구조물/장식(object)과 혼동을 막으려 예시를 붙인다.
  tool: '급여 도구 (숟가락·주사기·핀셋 등)',
  object: '일반 사물 (장식물·은신처·나뭇가지 등)',
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

// 촬영 환경은 필수 확인 항목이다(설계 §6.1). 저장 enum(ContextTag)에 none 을 추가하지 않고,
// 화면에서 '해당 없음'을 직접 고르면 기존 저장값인 빈 배열([])을 확정 상태로 쓴다(설계 §4.1).
export const CONTEXT_TAGS_TITLE = '촬영 환경 (필수)';
export const CONTEXT_TAGS_HELP =
  '영상에 해당하는 환경을 모두 골라줘. 해당하는 항목이 없으면 ‘해당 없음’을 선택해.';
// UI 전용 선택지 — ContextTag 가 아니며 API payload 에 문자열로 보내지 않는다(설계 §8).
export const CONTEXT_TAGS_NONE_LABEL = '해당 없음';

// 대표 행동 대상 영역의 사물/급여 도구 경계 안내문(설계 §6.3). 화면 문구에 backtick 을 쓰지 않는다(하드닝 §7).
export const TARGET_TOOL_OBJECT_NOTE =
  '먹이를 직접 전달하는 데 사용한 물건은 ‘급여 도구’, 사육장 안의 구조물이나 장식은 ‘일반 사물’을 골라줘.';

// ── 놀이 상호작용 방법 ────────────────────────────────────────────
// 피드백 출력·GtSummary 용 짧은 라벨. 저장 enum → 한국어 한 단어. 이 map 은 유지한다.
export const INTERACTION_LABELS: Record<InteractionType, string> = {
  ride: '올라타기',
  push: '밀기',
  rotate: '회전시키기',
  chase: '쫓기',
  repeated_return: '반복해서 돌아오기',
  other: '기타',
};

// ── 놀이 상호작용 입력 화면 전용 표시 계약(설계 §5.2) ────────────────
// INTERACTION_LABELS(피드백 출력용 짧은 라벨)와 역할이 다르다. 입력 카드는 라벨러가 여섯 항목의
// 관찰 기준을 읽는 순간 구분하도록 제목 + 설명을 함께 보여준다. 저장 enum·API payload 는 불변이고,
// 이 계약은 입력 화면 표시에만 쓴다(설계 §6 구현 경계).
export interface InteractionChoiceCopy {
  title: string;
  description: string;
}

// 기본(비-wheel) 문구. wheel 문맥에서는 '물체'를 '쳇바퀴'로 치환해 보여준다(§5.2).
const INTERACTION_CHOICE_COPY: Record<InteractionType, InteractionChoiceCopy> = {
  ride: {
    title: '위·안에 올라감',
    description: '몸이나 발을 물체 위 또는 안에 올렸어요.',
  },
  push: {
    title: '밖에서 밀거나 건드림',
    description: '올라타지 않고 발·머리·몸으로 물체를 밀었어요.',
  },
  rotate: {
    title: '물체를 실제로 돌림',
    description: '게코의 움직임 때문에 물체가 회전했어요.',
  },
  chase: {
    title: '움직이는 물체를 따라감',
    description: '돌아가거나 움직이는 물체를 쫓아갔어요.',
  },
  repeated_return: {
    title: '떠났다가 다시 찾아옴',
    description: '다른 곳에 갔다가 같은 물체로 여러 번 돌아왔어요.',
  },
  other: {
    title: '다른 방식으로 상호작용함',
    description: '위 설명에는 없지만 물체를 분명히 사용했어요.',
  },
};

// wheel 은 자주 확인하는 ride/push/rotate 를 먼저 보여주고(§5.1), 나머지는 보조 그룹으로 분리한다.
const WHEEL_PRIMARY_INTERACTIONS: readonly InteractionType[] = ['ride', 'push', 'rotate'];
const WHEEL_SECONDARY_INTERACTIONS: readonly InteractionType[] = [
  'chase',
  'repeated_return',
  'other',
];

// wheel 문맥의 화면 사물 명사. 비-wheel 은 카드 문구와 일치하도록 일반 명사 '물체'를 쓴다(§5.2).
function interactionObjectNoun(enrichmentObject: EnrichmentObject): string {
  return enrichmentObject === 'wheel' ? '쳇바퀴' : '물체';
}

// 입력 카드 문구. wheel 이면 '물체'를 '쳇바퀴'로 바꾼 새 객체를 반환한다(§5.2). 원본 map 은 mutate 하지 않는다.
export function interactionChoiceCopy(
  type: InteractionType,
  enrichmentObject: EnrichmentObject,
): InteractionChoiceCopy {
  const base = INTERACTION_CHOICE_COPY[type];
  if (enrichmentObject !== 'wheel') return { ...base };
  return {
    title: base.title.replaceAll('물체', '쳇바퀴'),
    description: base.description.replaceAll('물체', '쳇바퀴'),
  };
}

// 사물별 카드 그룹(§5.1). wheel 만 primary/secondary 로 나누고, 다른 사물은 여섯 항목을 한 목록(primary)으로 준다.
// 외부에서 배열 원본을 못 바꾸도록 항상 새 배열을 반환한다.
export function interactionChoiceGroups(enrichmentObject: EnrichmentObject): {
  primary: InteractionType[];
  secondary: InteractionType[];
} {
  if (enrichmentObject === 'wheel') {
    return {
      primary: [...WHEEL_PRIMARY_INTERACTIONS],
      secondary: [...WHEEL_SECONDARY_INTERACTIONS],
    };
  }
  return {
    primary: [...WHEEL_PRIMARY_INTERACTIONS, ...WHEEL_SECONDARY_INTERACTIONS],
    secondary: [],
  };
}

// 선택 즉시 보여주는 자연어 요약(설계 §4.4·§5.2). 전달된 선택 순서를 그대로 보존하고 임의 정렬하지 않는다.
// 각 항목은 문맥 제목이 사물 명사를 이미 담고 있으면 그대로 쓰고, 아니면 사물 명사를 앞에 붙여 스스로 설명되게 한다.
// (예: wheel + ride → '쳇바퀴 위·안에 올라감', wheel + rotate → '쳇바퀴를 실제로 돌림')
export function interactionSelectionSummary(
  enrichmentObject: EnrichmentObject,
  selected: readonly InteractionType[],
): string | null {
  if (!selected || selected.length === 0) return null;
  const noun = interactionObjectNoun(enrichmentObject);
  const parts = selected.map((type) => {
    const { title } = interactionChoiceCopy(type, enrichmentObject);
    return title.includes(noun) ? title : `${noun} ${title}`;
  });
  return `선택한 내용: ${parts.join(' · ')}`;
}

// ── 쳇바퀴 상호작용 단계형 질문(설계 §4.7) ───────────────────────
// 쳇바퀴는 접촉 방식(ride/push)과 결과(rotate)를 같은 위계로 나열하지 않고, 관찰 순서대로
// 예/아니오 질문으로 묻는다. 저장 enum·payload 는 불변이고, 이 계약은 입력 화면 표시에만 쓴다.
export interface WheelInteractionQuestion {
  title: string;
  selectedLabel: string;
}

const WHEEL_INTERACTION_QUESTIONS: Record<InteractionType, WheelInteractionQuestion> = {
  ride: { title: '게코가 쳇바퀴 위나 안에 올라가 있었어?', selectedLabel: '올라가 있었어' },
  rotate: { title: '쳇바퀴가 실제로 돌아갔어?', selectedLabel: '돌아갔어' },
  push: { title: '게코가 밖에서 쳇바퀴를 밀거나 건드렸어?', selectedLabel: '밀거나 건드렸어' },
  chase: { title: '움직이는 쳇바퀴를 따라갔어?', selectedLabel: '따라갔어' },
  repeated_return: { title: '떠났다가 다시 돌아왔어?', selectedLabel: '다시 돌아왔어' },
  other: { title: '다른 방식으로 상호작용했어?', selectedLabel: '다른 방식으로 함' },
};

export function wheelInteractionQuestion(type: InteractionType): WheelInteractionQuestion {
  return { ...WHEEL_INTERACTION_QUESTIONS[type] };
}

// 관찰 순서: ride → rotate → push 를 먼저 묻고, chase/repeated_return/other 는 보조 그룹으로.
// 항상 새 배열을 반환한다(외부 mutate 방지).
const WHEEL_PRIMARY_QUESTIONS: readonly InteractionType[] = ['ride', 'rotate', 'push'];
const WHEEL_SECONDARY_QUESTIONS: readonly InteractionType[] = ['chase', 'repeated_return', 'other'];

export function wheelInteractionGroups(): {
  primary: InteractionType[];
  secondary: InteractionType[];
} {
  return { primary: [...WHEEL_PRIMARY_QUESTIONS], secondary: [...WHEEL_SECONDARY_QUESTIONS] };
}

// 이미 보조 enum(chase/repeated_return/other)이 선택돼 있으면 보조 영역을 펼쳐야 한다.
// (비동기로 복원된 draft 도 올바르게 펼쳐지도록 컴포넌트가 이 결과와 disclosure 상태를 OR 한다.)
export function shouldOpenSecondaryWheelChoices(selected: readonly InteractionType[]): boolean {
  const secondary = new Set<InteractionType>(WHEEL_SECONDARY_QUESTIONS);
  return (selected ?? []).some((s) => secondary.has(s));
}

// 쳇바퀴 구간 종료시간 아래에 항상 보여주는 승인된 두 문장(설계 §4.7). '떠남' enum 을 만들지 않고,
// 종료 시점과 '계속 상호작용 중' 기준을 안내한다.
export const WHEEL_SEGMENT_END_HELP: readonly string[] = [
  '게코가 쳇바퀴에서 내려온 뒤 더 이상 쳇바퀴와 상호작용하지 않는 순간을 종료 시점으로 표시해.',
  '내려온 뒤에도 밖에서 밀거나 건드리면 상호작용이 계속되는 중이야.',
];

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

// ── 활동 강도(legacy read 전용, 설계 §6.3) ───────────────────────
// 신규 GT 는 highlight_recommendation 을 쓰지만, 과거 v1 GT 는 activity_intensity 를 갖는다.
// GtSummary 가 legacy GT 를 한국어로 보여줄 때만 쓴다(하드닝 §1).
export const ACTIVITY_INTENSITY_LABELS: Record<ActivityIntensity, string> = {
  low: '낮음',
  medium: '보통',
  high: '높음',
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
  // 그림자·조명 노이즈와 실제 게코 이동을 구분한다(설계 §5.2·§6.2).
  moving: '게코가 실제로 위치를 옮기거나 등반하거나 자세를 바꾸는 장면. 그림자나 조명만 변하고 게코가 가만히 있으면 휴식이야.',
  // 과대 추론(물이 안 보여도 물 마시기로 단정)을 막는다(하드닝 §7).
  drinking: '물·물그릇·젖은 표면 등에 입이 실제로 닿아 반복해서 핥는 장면.',
  hand_feeding: '사람이 손이나 급여 도구로 먹이를 직접 먹이는 장면.',
  shedding: '허물이 실제로 벗겨지는 장면.',
  // basking 저장 키는 화면에서 '휴식' — 열원 아래 일광욕으로 좁히지 않는다(설계 §4.2·§6.2).
  basking: '게코가 위치를 옮기거나 뚜렷한 행동을 하지 않고 가만히 쉬는 장면. 그림자나 조명만 변하고 게코가 움직이지 않았다면 휴식이야.',
  eating_paste: '그릇에 제공된 슈퍼푸드를 게코가 스스로 핥아 먹는 장면.',
  eating_prey: '게코가 곤충을 추적·포획하거나 삼키는 장면.',
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
  description: '손을 사용해 직접 먹였는지, 급여 도구를 사용해 먹였는지 골라.',
};
const TARGET_PROMPT_DEFAULT: TargetPrompt = {
  title: '이 행동은 무엇을 향했나?',
  description: '게코가 대표 행동을 하면서 직접 닿거나 향한 대상을 골라.',
};

// 세 대표 행동 모두에 붙는 공통 보조 설명(§5.3). 쳇바퀴/장난감은 대상이 아니라 놀이 근거.
// 화면에 backtick 이 그대로 보이지 않도록 마크다운 강조 문자를 쓰지 않는다(하드닝 §7).
export const TARGET_PROMPT_COMMON_NOTE =
  '쳇바퀴나 장난감을 사용한 행동은 아래 놀이 행동 근거에 기록해.';

export function targetPromptFor(primaryAction: PrimaryAction): TargetPrompt {
  if (primaryAction === 'drinking') return TARGET_PROMPT_DRINKING;
  if (primaryAction === 'hand_feeding') return TARGET_PROMPT_HAND_FEEDING;
  return TARGET_PROMPT_DEFAULT;
}

// ── 숫자 시간 포맷(설계 §5.2·§7 · 하드닝 §2) ─────────────────────
// 화면·해설의 시간은 소수점 첫째 자리까지만. 서버 저장 정밀도는 건드리지 않는다.
// 예) 31.7999 → '31.8', 0 → '0.0'.
export function formatSeconds(sec: number): string {
  if (!Number.isFinite(sec)) return '0.0';
  return (Math.round(sec * 10) / 10).toFixed(1);
}

// '영상 시작/끝' 판정은 반올림된 표시값이 아니라 실제 clip duration 을 기준으로 한다(하드닝 §2).
// 저장 정밀도(31.7999)를 그대로 쓰되, float 오차·표시 반올림 폭(0.1초)의 절반만 허용한다.
export const VIDEO_EDGE_EPSILON = 0.05;

export function isVideoStart(startSec: number): boolean {
  // 음수(-0.1 등 범위 밖)는 영상 시작이 아니다.
  return Number.isFinite(startSec) && startSec >= 0 && startSec <= VIDEO_EDGE_EPSILON;
}

export function isVideoEnd(
  endSec: number,
  durationSec: number | null | undefined,
): boolean {
  if (!Number.isFinite(endSec)) return false;
  if (durationSec == null || !Number.isFinite(durationSec) || durationSec < 0) return false;
  // 실제 duration 기준 ±ε 창 안일 때만 '영상 끝'. 31.7999·legacy 31.8 은 인정하되,
  // duration 을 크게 초과한 값(duration+1 등)은 끝으로 보지 않는다.
  return (
    endSec >= durationSec - VIDEO_EDGE_EPSILON &&
    endSec <= durationSec + VIDEO_EDGE_EPSILON
  );
}

// 시간 구간을 사람이 읽는 문장으로(하드닝 §2). duration 을 알면 시작/끝을 '영상 전체/시작/끝'으로.
// 예) (0, 31.7999, 31.7999) → '영상 전체', (13, 31.7999, 31.7999) → '13.0초부터 영상 끝까지'.
export function formatTimeRange(
  startSec: number,
  endSec: number,
  durationSec?: number | null,
): string {
  const atStart = isVideoStart(startSec);
  const atEnd = isVideoEnd(endSec, durationSec);
  if (atStart && atEnd) return '영상 전체';
  if (atStart) return `영상 시작부터 ${formatSeconds(endSec)}초까지`;
  if (atEnd) return `${formatSeconds(startSec)}초부터 영상 끝까지`;
  return `${formatSeconds(startSec)}초부터 ${formatSeconds(endSec)}초까지`;
}

// 입력 화면에서 '영상 끝'을 나타내는 라벨. raw 31.7999 대신 '영상 끝 (31.8초)'(하드닝 §2).
export function formatVideoEndLabel(durationSec: number): string {
  return `영상 끝 (${formatSeconds(durationSec)}초)`;
}

// segment 를 사람이 읽는 문장으로(설계 §4.5·§7 · 하드닝 §2). 예) '핥기 · 영상 전체'.
// 라벨링 화면·사람 판정 요약·튜토리얼 해설이 모두 이 formatter 를 공유한다(하드닝 §2).
export function describeSegment(
  segment: ActionSegment,
  durationSec?: number | null,
): string {
  const label = OBSERVED_LABELS[segment.action] ?? UNKNOWN_LABEL;
  return `${label} · ${formatTimeRange(segment.start_sec, segment.end_sec, durationSec)}`;
}

// ── 사람용 값 표시(설계 §4.5·§7) ─────────────────────────────────
// 배열은 한국어 항목을 쉼표로 잇고, none/null/빈값은 '없음'으로 보여준다.
// raw 값은 절대 그대로 렌더하지 않고 label map 을 통과시킨다.
// map 에 없는 값은 raw 영문 대신 '확인 필요'로(하드닝 §7).
function labelWith(map: Record<string, string>, value: string): string {
  return map[value] ?? UNKNOWN_LABEL;
}

function formatList(values: readonly string[], map: Record<string, string>): string {
  if (!values || values.length === 0) return '없음';
  return values.map((v) => labelWith(map, v)).join(', ');
}

// VLM 대표 행동을 라벨러 언어로(하드닝 §7). 미지 action(VLM 출력 클래스 등)은 '확인 필요'.
export function formatActionLabel(value: unknown): string {
  return ACTION_LABELS[String(value) as PrimaryAction] ?? UNKNOWN_LABEL;
}

// legacy activity_intensity 를 한국어로(하드닝 §1). 미지 값은 '확인 필요'.
export function formatActivityIntensity(value: unknown): string {
  return ACTIVITY_INTENSITY_LABELS[String(value) as ActivityIntensity] ?? UNKNOWN_LABEL;
}

// 사람 판정 요약(GtSummary)의 하이라이트/활동강도 문구(하드닝 §1).
// - 신규 GT: 유효한 highlight → '하이라이트 포함/애매/제외'
// - legacy GT: highlight 없음 → 있으면 '활동 강도 낮음/보통/높음', 없으면 null(항목 생략)
// 어떤 경우에도 undefined 를 렌더하지 않는다.
export function highlightSummaryClause(gt: {
  highlight_recommendation?: unknown;
  activity_intensity?: unknown;
}): string | null {
  if (isValidHighlight(gt.highlight_recommendation)) {
    return `하이라이트 ${HIGHLIGHT_LABELS[gt.highlight_recommendation]}`;
  }
  if (gt.activity_intensity != null) {
    return `활동 강도 ${formatActivityIntensity(gt.activity_intensity)}`;
  }
  return null;
}

// 튜토리얼 피드백 dimension 값 → 한국어 문장(설계 §4.5). key 별로 알맞은 label map/formatter 를 고른다.
// segments 는 duration 을 알면 '영상 전체/끝'까지 표시한다(하드닝 §2 · 라벨링 화면과 같은 formatter).
export function formatDimensionValue(
  key: string,
  value: unknown,
  durationSec?: number | null,
): string {
  if (value === null || value === undefined || value === '') return '없음';
  if (key === 'segments' && Array.isArray(value)) {
    return value.length
      ? (value as ActionSegment[]).map((s) => describeSegment(s, durationSec)).join(', ')
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
      // 알 수 없는 dimension 은 raw JSON·raw enum 을 노출하지 않는다(하드닝 §7).
      // 정상 흐름에선 위 case 로 전부 처리되며, 여기는 방어용이다.
      if (Array.isArray(value)) return value.length ? UNKNOWN_LABEL : '없음';
      if (typeof value === 'object') return '없음';
      return UNKNOWN_LABEL;
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

// 알 수 없는 dimension key 도 raw key 를 노출하지 않는다(하드닝 §7).
export function dimensionLabel(key: string): string {
  return DIMENSION_LABELS[key] ?? UNKNOWN_LABEL;
}
