// 그룹 이중 블라인드 라벨링의 "순수" 도메인 계약(설계 §3·§5).
// 여기에는 DB·네트워크·React 의존이 전혀 없다 — 활동일 계산과 결정론적 비교기만
// 담아 클라이언트/서버/테스트가 같은 규칙을 공유한다.
// (TS 배경 비유: 순수 util 모듈 — NestJS 의 service 가 아니라 domain helper.)

import {
  GROUND_TRUTH_FIELD_ORDER,
  isValidGroundTruthShape,
  type ActionSegment,
  type GroundTruthInput,
} from './labelingV2';

// 비교기 버전. 결과에 함께 저장해 나중에 규칙이 바뀌어도 어느 버전으로 합의했는지
// 추적할 수 있게 한다(설계 §5.2 "비교 버전을 결과에 저장").
export const BLIND_COMPARATOR_VERSION = 'motion-blind-v1' as const;

export type BlindDecision = 'label' | 'hold' | 'exclude';

// 제출 사유 코드. exclude/hold 사유를 저장하지만 합의 비교에는 쓰지 않는다
// (둘 다 exclude 면 사유가 달라도 일치 — 설계 §5.2 규칙 2).
export type BlindReasonCode =
  | 'behavior_data'
  | 'ambiguous'
  | 'gecko_absent'
  | 'capture_error'
  | 'media_error';

// 한 라벨러의 immutable 최초 제출(설계 §3.2). AI/VLM 이후 수정값(current_gt)·
// prediction·evidence 는 이 타입에 들어올 수 없다(설계 §5.2).
export interface BlindSubmissionInput {
  decision: BlindDecision;
  initial_gt: GroundTruthInput | null;
  note: string | null;
  reason_code: BlindReasonCode;
}

export interface BlindComparison {
  status: 'agreed' | 'conflict';
  final_decision: BlindDecision | null;
  final_gt: GroundTruthInput | null;
  differing_fields: string[];
  comparator_version: typeof BLIND_COMPARATOR_VERSION;
}

export interface BlindDecisionCopyEntry {
  title: string;
  description: string;
}

// 라벨러 화면의 세 판정 버튼 문구(설계 §4.2). 내부 용어(triage/consensus/slot)는
// 절대 노출하지 않는다.
export const BLIND_DECISION_COPY: Record<BlindDecision, BlindDecisionCopyEntry> = {
  label: {
    title: '라벨링하기',
    description: '게코의 의미 있는 행동이 보여서 행동과 시간을 기록해야 해',
  },
  hold: {
    title: '보류하기',
    description: '영상이 애매해 지금은 확정 행동 라벨을 만들기 어려워',
  },
  exclude: {
    title: '제외하기',
    description: '게코가 없거나 촬영·재생 오류라 행동 데이터로 쓸 수 없어',
  },
};

const ACTIVITY_DAY_RE = /^\d{4}-\d{2}-\d{2}$/;

// 활동일(YYYY-MM-DD) 의 UTC 경계. 활동일 D = [D 07:00 KST, D+1 07:00 KST).
// KST = UTC+9 이므로 D 07:00 KST = (D-1) 22:00 UTC.
export function activityDayBounds(day: string): { from: string; to: string } {
  if (!ACTIVITY_DAY_RE.test(day)) {
    throw new Error('invalid_activity_day');
  }
  // `${day}T07:00:00+09:00` 로 KST 07:00 을 명시하면 브라우저 로컬 타임존과 무관하게
  // 결정론적으로 UTC 경계가 나온다.
  const from = new Date(`${day}T07:00:00+09:00`);
  if (Number.isNaN(from.getTime())) {
    throw new Error('invalid_activity_day');
  }
  const to = new Date(from.getTime() + 24 * 60 * 60 * 1000);
  return { from: from.toISOString(), to: to.toISOString() };
}

// 어떤 UTC 시각이 속한 활동일. 설계 식 `(ts AT TIME ZONE 'Asia/Seoul' - 7h)::date`
// 와 동치다. KST(=UTC+9) 로 옮긴 뒤 7시간을 빼면 (UTC + 2h) 의 날짜와 같다.
export function currentActivityDay(now: Date): string {
  const shifted = new Date(now.getTime() + 2 * 60 * 60 * 1000);
  return shifted.toISOString().slice(0, 10);
}

// 제출 입력 유효성(설계 §3.2·§5.2). label 은 유효한 GT 를 요구하고, 비-label 은
// GT 를 가지면 안 된다. 정상 클라이언트에선 안 나오는 malformed payload 를 막는다.
export function validateBlindSubmissionInput(input: BlindSubmissionInput): void {
  if (input.decision === 'label' && !isValidGroundTruthShape(input.initial_gt)) {
    throw new Error('label_requires_valid_initial_gt');
  }
  if (input.decision !== 'label' && input.initial_gt !== null) {
    throw new Error('non_label_forbids_initial_gt');
  }
}

// 비교에 쓰는 GT 필드 순서. GroundTruthInput 선언 순서를 그대로 따르되 note 는
// 제외한다(자유 메모는 비교에서 빼고 원문만 보존 — 설계 §5.2).
const GT_COMPARE_FIELDS = [
  'visibility',
  'primary_action',
  'observed_actions',
  'segments',
  'target',
  'human_confidence',
  'context_tags',
  'activity_intensity',
  'highlight_recommendation',
  'enrichment_object',
  'interaction_types',
] as const;

const SET_FIELDS = new Set<string>(['observed_actions', 'context_tags', 'interaction_types']);

// 배열을 중복 제거 + canonical sort 한 뒤 문자열로 눌러 집합 비교(설계 §5.2).
// 구분자는 enum 값에 등장하지 않는 문자로 골라 오탐을 막는다.
function canonicalSet(values: readonly string[]): string {
  return Array.from(new Set(values)).sort().join('|');
}

// 초 단위 시간을 정수 millisecond 로 정규화한다(설계 §5.2).
function toMs(value: number): number {
  return Math.round(value * 1000);
}

// segment 배열 비교: 개수·순서·대응 행동이 같아야 하고, 각 경계 차이가 500ms 이하면
// 같다(설계 §5.2). 순서를 보존한다(sort 하지 않는다).
function segmentsEqual(a: ActionSegment[], b: ActionSegment[]): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i += 1) {
    if (a[i].action !== b[i].action) return false;
    if (Math.abs(toMs(a[i].start_sec) - toMs(b[i].start_sec)) > 500) return false;
    if (Math.abs(toMs(a[i].end_sec) - toMs(b[i].end_sec)) > 500) return false;
  }
  return true;
}

function gtFieldEqual(field: string, a: GroundTruthInput, b: GroundTruthInput): boolean {
  if (field === 'segments') {
    return segmentsEqual(a.segments, b.segments);
  }
  if (SET_FIELDS.has(field)) {
    const av = a[field as keyof GroundTruthInput] as unknown as string[];
    const bv = b[field as keyof GroundTruthInput] as unknown as string[];
    return canonicalSet(av) === canonicalSet(bv);
  }
  // scalar 필드는 exact match.
  return a[field as keyof GroundTruthInput] === b[field as keyof GroundTruthInput];
}

// 두 immutable 최초 제출을 결정론적으로 비교한다(설계 §5.2). 이 함수만이 합의 상태를
// 만들고, 어떤 상태도 임의로 덮지 않는다.
export function compareBlindSubmissions(
  a: BlindSubmissionInput,
  b: BlindSubmissionInput,
): BlindComparison {
  validateBlindSubmissionInput(a);
  validateBlindSubmissionInput(b);

  // 규칙 1: decision 이 다르면 불일치.
  if (a.decision !== b.decision) {
    return {
      status: 'conflict',
      final_decision: null,
      final_gt: null,
      differing_fields: ['decision'],
      comparator_version: BLIND_COMPARATOR_VERSION,
    };
  }

  // 규칙 2: 둘 다 exclude 또는 둘 다 hold → 일치(사유 코드 무관).
  if (a.decision === 'exclude' || a.decision === 'hold') {
    return {
      status: 'agreed',
      final_decision: a.decision,
      final_gt: null,
      differing_fields: [],
      comparator_version: BLIND_COMPARATOR_VERSION,
    };
  }

  // 규칙 3: 둘 다 label → GT 필드 비교. validate 를 통과했으니 non-null 이 보장된다.
  const gtA = a.initial_gt as GroundTruthInput;
  const gtB = b.initial_gt as GroundTruthInput;
  const differing = GT_COMPARE_FIELDS.filter((field) => !gtFieldEqual(field, gtA, gtB));

  if (differing.length === 0) {
    return {
      status: 'agreed',
      final_decision: 'label',
      // 원문 note 를 보존한 채 a 의 제출을 최종 GT 로 채택한다(둘이 동치이므로 무방).
      final_gt: gtA,
      differing_fields: [],
      comparator_version: BLIND_COMPARATOR_VERSION,
    };
  }

  return {
    status: 'conflict',
    final_decision: null,
    final_gt: null,
    differing_fields: [...differing],
    comparator_version: BLIND_COMPARATOR_VERSION,
  };
}

// 폼 위→아래 순서로 differing 필드를 정렬할 때 참조할 수 있는 공개 순서.
// (GROUND_TRUTH_FIELD_ORDER 는 note/activity_intensity 를 포함하지 않으므로 재노출한다.)
export const BLIND_GT_COMPARE_FIELD_ORDER: readonly string[] = GT_COMPARE_FIELDS;

// GROUND_TRUTH_FIELD_ORDER 를 참조만 하고 있음을 명시(미사용 import 경고 방지 겸
// 필드 순서가 폼 계약과 어긋나지 않는지 개발 중 교차 확인용).
void GROUND_TRUTH_FIELD_ORDER;
