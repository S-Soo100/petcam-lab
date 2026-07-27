// 그룹 이중 블라인드 라벨러 화면의 "순수 표시 계약"(설계 §4·§9).
//
// React 상태·네트워크 없이 문구·진행 라인·빈 상태·제출 결과 메시지를 만든다. 상대 판정 원문은
// 어떤 함수도 받지 않는다 — 집계 숫자만 다룬다(설계 §5.1). 내부 용어(triage/consensus/slot)는
// 화면에 노출하지 않는다(§9).

import type { BlindWorkspace } from '@/lib/motionBlindReviewServer';
import type { BlindSubmitResult, OwnerSubmissionView } from '@/lib/motionBlindReviewApi';
import { BLIND_DECISION_COPY, type BlindDecision } from '@/lib/motionBlindReview';
import {
  UNKNOWN_LABEL,
  formatActivityIntensity,
  formatDimensionValue,
} from '@/lib/labelingDisplay';

// 첫 접속 안내 세 문장(설계 §4.1). 다시 열 수 있고, 닫았다는 상태만 사용자별로 저장한다.
export const BLIND_ONBOARDING_SENTENCES: readonly string[] = [
  '같은 영상을 두 사람이 따로 확인해.',
  '라벨러 화면에는 상대방의 답이 보이지 않아.',
  '두 답이 같으면 자동 완료되고, 다르면 관리자가 확인해.',
];

export const BLIND_ONBOARDING_START = '작업 시작';
export const BLIND_ONBOARDING_REOPEN = '작업 방법';

// localStorage 키 — 사용자별 격리(설계 §9). 저장 실패는 큐를 막지 않는다.
export function blindOnboardingKey(userId: string): string {
  return `petcam-blind-onboarding:v1:${userId}`;
}

// 진행 라인 — 집계만(설계 §4.4·§5.1). own 은 본인 처리 건수, group 은 비교 상태 집계.
// ⚠️ 상대 라벨러의 제출 여부·진행 순서는 오늘 작업 화면에 표시하지 않는다(설계 §5.1) — partner 라인 제거.
export interface BlindProgressLines {
  own: string;
  group: string;
}

export function blindProgressLines(ws: BlindWorkspace): BlindProgressLines {
  return {
    own: `내 작업 ${ws.own_submitted}/${ws.clip_total}`,
    group: `그룹 합의 ${ws.agreed_count} · 불일치 ${ws.conflict_count} · 비교 대기 ${ws.awaiting_count}`,
  };
}

// '오늘 작업' 제목(설계 §5.1). 기준일은 달력의 오늘이 아니라 가장 최근에 닫힌 활동일이다.
// '2026-07-22' → '7월 22일 오늘 작업'.
export function blindTodayTitle(day: string | null): string {
  if (!day) return '오늘 작업';
  const [, m, d] = day.split('-').map(Number);
  return `${m}월 ${d}일 오늘 작업`;
}

// 활동일 경계 안내(설계 §3.1·§5.1). 07:00 KST ~ 다음 날 07:00 KST.
export const BLIND_TODAY_WINDOW_HINT = '활동일 07:00 ~ 다음 날 07:00';

// 우선 활동일 헤더(설계 §4.1). '2026-07-22' → '7월 22일 07:00 ~ 7월 23일 07:00'.
export function blindActivityDayHeader(day: string | null): string | null {
  if (!day) return null;
  const [y, m, d] = day.split('-').map(Number);
  const next = new Date(Date.UTC(y, m - 1, d + 1));
  const nm = next.getUTCMonth() + 1;
  const nd = next.getUTCDate();
  return `우선 작업: ${m}월 ${d}일 07:00 ~ ${nm}월 ${nd}일 07:00`;
}

// 빈 큐/완료 안내(설계 §11). 오늘 작업 0건 → 완료 문구. 미배정은 별도 안내.
export function blindEmptyStateMessage(ws: BlindWorkspace): string | null {
  if (!ws.group_id) {
    return '담당 카메라가 아직 배정되지 않았어. 관리자에게 문의해.';
  }
  if (!ws.priority_activity_day) {
    return '오늘 할 라벨링을 모두 끝냈어.';
  }
  return null;
}

// 완료 후 이전 미완료 활동일 진입 CTA(설계 §5.1·§11). 남은 과거 활동일이 있을 때만.
// 자동으로 날짜를 건너뛰지 않고, 사용자가 명시적으로 눌러 이동한다.
export function blindPreviousWorkCta(ws: BlindWorkspace): string | null {
  return ws.available_days.length > 0 ? '이전 활동일 작업 보기' : null;
}

// 다음으로 열 활동일 = 현재 작업일보다 오래된, 남은 미완료 활동일 중 가장 최신(설계 §5.1).
export function blindNextAvailableDay(ws: BlindWorkspace, currentDay: string | null): string | null {
  const older = ws.available_days.filter((d) => currentDay === null || d < currentDay);
  return older.length > 0 ? older[0] : null;
}

// 제출 판정 사유 코드 → 사람이 읽는 문구(내 기록 표시용).
const BLIND_REASON_COPY: Record<string, string> = {
  behavior_data: '행동 데이터',
  ambiguous: '모호함',
  gecko_absent: '게코 없음',
  capture_error: '촬영 오류',
  media_error: '재생 오류',
};

export function blindReasonCopy(code: string): string {
  return BLIND_REASON_COPY[code] ?? code;
}

// 늦은 clip 배지(설계 §4.3). 이미 개방된 과거 날짜를 되돌리지 않고 최우선 표시만.
export function blindLateAddedBadge(ws: BlindWorkspace): string | null {
  return ws.late_added_count > 0 ? `어제 추가 ${ws.late_added_count}건` : null;
}

// 제출 후 메시지(설계 §4.2). 상대 실제 선택은 노출하지 않는다 — 세 축만.
export function blindSubmitResultMessage(result: BlindSubmitResult): string {
  switch (result.status) {
    case 'agreed':
      return '두 판정 일치';
    case 'conflict':
      return '관리자 확인으로 보냈어';
    default:
      return '저장 완료 · 상대 판정 대기 중';
  }
}

// ── owner 불일치 검수 화면 문구(설계 §4.5) ────────────────────────
export const OWNER_CONFLICT_TITLE = '불일치 검수';
export const OWNER_GROUP_TITLE = '그룹 배정';
export const OWNER_DIFFERING_TITLE = '서로 다른 항목';
export const OWNER_RESOLVE_LABELS: { a: string; b: string; new: string } = {
  a: 'A 판정 채택',
  b: 'B 판정 채택',
  new: '새 판정 저장',
};

// differing_fields(내부 필드명) → 사람이 읽는 항목명. 내부 용어를 그대로 노출하지 않는다.
const DIFFERING_FIELD_LABELS: Record<string, string> = {
  decision: '최종 판정(라벨/보류/제외)',
  visibility: '게코가 보이는지',
  primary_action: '대표 행동',
  observed_actions: '실제 동작',
  segments: '동작과 시간',
  target: '행동 대상',
  human_confidence: '판단 확실도',
  context_tags: '촬영 환경',
  activity_intensity: '활동 강도',
  highlight_recommendation: '하이라이트 여부',
  enrichment_object: '놀이에 사용한 사물',
  interaction_types: '놀이에 사용한 방법',
};

export function ownerDifferingFieldLabels(fields: readonly string[]): string[] {
  return fields.map((f) => DIFFERING_FIELD_LABELS[f] ?? UNKNOWN_LABEL);
}

export interface OwnerDifferenceRow {
  key: string;
  label: string;
  aValue: string;
  bValue: string;
}

function ownerDifferenceValue(
  field: string,
  submission: OwnerSubmissionView | null,
  durationSec: number,
): string {
  if (!submission) return '제출 없음';
  if (!(field in DIFFERING_FIELD_LABELS)) return UNKNOWN_LABEL;
  if (field === 'decision') {
    return BLIND_DECISION_COPY[submission.decision as BlindDecision]?.title ?? UNKNOWN_LABEL;
  }

  const gt =
    submission.initial_gt && typeof submission.initial_gt === 'object' && !Array.isArray(submission.initial_gt)
      ? (submission.initial_gt as Record<string, unknown>)
      : null;
  if (!gt) return '없음';
  const value = gt[field];
  if (field === 'context_tags' && Array.isArray(value) && value.length === 0) {
    return '해당 없음';
  }
  if (field === 'activity_intensity') {
    return value == null ? '없음' : formatActivityIntensity(value);
  }
  return formatDimensionValue(field, value, durationSec);
}

// Owner가 DB를 따로 보지 않고 같은 화면에서 A/B의 실제 차이를 비교하도록 만든다.
// differing_fields allowlist 밖의 값은 raw 내부명을 숨기고 '확인 필요'로 닫는다.
export function ownerDifferenceRows(
  fields: readonly string[],
  submissionA: OwnerSubmissionView | null,
  submissionB: OwnerSubmissionView | null,
  durationSec: number,
): OwnerDifferenceRow[] {
  return fields.map((field) => ({
    key: field,
    label: DIFFERING_FIELD_LABELS[field] ?? UNKNOWN_LABEL,
    aValue: ownerDifferenceValue(field, submissionA, durationSec),
    bValue: ownerDifferenceValue(field, submissionB, durationSec),
  }));
}

// exclude 세부 사유(설계 §4.2·§4.5).
export const BLIND_EXCLUDE_REASONS: readonly { code: 'gecko_absent' | 'capture_error' | 'media_error'; label: string }[] = [
  { code: 'gecko_absent', label: '게코가 없어' },
  { code: 'capture_error', label: '촬영 오류야' },
  { code: 'media_error', label: '재생 오류야' },
];
