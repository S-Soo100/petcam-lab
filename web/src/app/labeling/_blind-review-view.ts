// 그룹 이중 블라인드 라벨러 화면의 "순수 표시 계약"(설계 §4·§9).
//
// React 상태·네트워크 없이 문구·진행 라인·빈 상태·제출 결과 메시지를 만든다. 상대 판정 원문은
// 어떤 함수도 받지 않는다 — 집계 숫자만 다룬다(설계 §5.1). 내부 용어(triage/consensus/slot)는
// 화면에 노출하지 않는다(§9).

import type { BlindWorkspace } from '@/lib/motionBlindReviewServer';
import type { BlindSubmitResult } from '@/lib/motionBlindReviewApi';

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

// 진행 라인 — 집계만(설계 §4.4). own/partner 는 처리 건수, 그룹은 비교 상태 집계.
export interface BlindProgressLines {
  own: string;
  partner: string;
  group: string;
}

export function blindProgressLines(ws: BlindWorkspace): BlindProgressLines {
  return {
    own: `내 작업 ${ws.own_submitted}/${ws.clip_total}`,
    partner: `파트너 ${ws.partner_submitted}/${ws.clip_total}`,
    group: `그룹 합의 ${ws.agreed_count} · 불일치 ${ws.conflict_count} · 비교 대기 ${ws.awaiting_count}`,
  };
}

// 우선 활동일 헤더(설계 §4.1). '2026-07-22' → '7월 22일 07:00 ~ 7월 23일 07:00'.
export function blindActivityDayHeader(day: string | null): string | null {
  if (!day) return null;
  const [y, m, d] = day.split('-').map(Number);
  const next = new Date(Date.UTC(y, m - 1, d + 1));
  const nm = next.getUTCMonth() + 1;
  const nd = next.getUTCDate();
  return `우선 작업: ${m}월 ${d}일 07:00 ~ ${nm}월 ${nd}일 07:00`;
}

// 빈 큐/상태 안내(설계 §9). "왜 비었는지 + 다음 행동"을 말한다.
export function blindEmptyStateMessage(ws: BlindWorkspace): string | null {
  if (!ws.group_id) {
    return '담당 카메라가 아직 배정되지 않았어. 관리자에게 문의해.';
  }
  if (!ws.priority_activity_day) {
    // 내 몫을 다 끝냈다. 파트너가 남았으면 그 사실도 알린다(과거 작업 계속 가능).
    if (ws.awaiting_count > 0) {
      return '파트너 제출을 기다리는 중이야. 너는 과거 작업을 계속할 수 있어.';
    }
    return '어제 내 작업을 모두 끝냈어. 그 전날 작업을 시작할 수 있어.';
  }
  return null;
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

// exclude 세부 사유(설계 §4.2·§4.5).
export const BLIND_EXCLUDE_REASONS: readonly { code: 'gecko_absent' | 'capture_error' | 'media_error'; label: string }[] = [
  { code: 'gecko_absent', label: '게코가 없어' },
  { code: 'capture_error', label: '촬영 오류야' },
  { code: 'media_error', label: '재생 오류야' },
];
