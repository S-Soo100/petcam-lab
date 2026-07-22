// 분류 결과 확인 Card 의 표시 규칙 — 순수 view-model(설계 §7.2·§7.3).
//
// React 렌더 테스트 환경이 없으므로 문구·CTA·다음 버튼 라벨·중복 클릭 방지·재시도 규칙을 JSX 와
// 분리해 vitest 로 직접 검증한다. 컴포넌트(_motion-review-continuation.tsx)는 이 함수를 소비한다.

import type { MotionLabelingState } from '@/lib/labelingV3';

export interface MotionContinuationInput {
  state: MotionLabelingState;
  nextBusy?: boolean;
  nextFailed?: boolean;
}

export interface MotionContinuationView {
  statusText: string;
  showGtCta: boolean;
  nextLabel: string;
  nextDisabled: boolean;
  showNextRetry: boolean;
}

const STATUS_TEXT: Record<MotionLabelingState, string> = {
  skip: '제외로 저장됨',
  hold: '보류로 저장됨',
  label: '라벨 대상으로 저장됨',
  unreviewed: '미분류로 되돌림',
};

export function motionContinuationView(input: MotionContinuationInput): MotionContinuationView {
  const isLabel = input.state === 'label';
  return {
    statusText: STATUS_TEXT[input.state],
    // label 은 GT 작성이 이어지므로 "지금 사람 판정 작성" CTA 를 보인다. hold/skip 은 GT 를 막는다.
    showGtCta: isLabel,
    // next 는 실패해도 저장은 유지되므로 문구를 바꾸지 않는다. label 은 GT 를 뒤로 미루는 뉘앙스.
    nextLabel: isLabel ? '나중에 라벨링하고 다음 영상' : '다음 미분류 영상',
    nextDisabled: !!input.nextBusy,
    showNextRetry: !!input.nextFailed,
  };
}
