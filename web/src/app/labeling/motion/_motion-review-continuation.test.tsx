import { describe, expect, it } from 'vitest';

import { motionContinuationView } from './_motion-review-continuation-view';

// React 렌더 환경이 없으므로 continuation Card 의 표시 규칙은 순수 view-model 로 분리해 검증한다.
// 상태 문구·GT CTA·다음 버튼 라벨·중복 클릭 방지·next 실패 시 재시도(설계 §7.2·§7.3).

describe('motionContinuationView', () => {
  it('skip → 제외로 저장됨, GT CTA 없음, 다음 미분류 영상', () => {
    const v = motionContinuationView({ state: 'skip' });
    expect(v.statusText).toBe('제외로 저장됨');
    expect(v.showGtCta).toBe(false);
    expect(v.nextLabel).toBe('다음 미분류 영상');
  });

  it('hold → 보류로 저장됨, GT CTA 없음', () => {
    const v = motionContinuationView({ state: 'hold' });
    expect(v.statusText).toBe('보류로 저장됨');
    expect(v.showGtCta).toBe(false);
  });

  it('label → 라벨 대상으로 저장됨, GT CTA 있음, 나중에 라벨링하고 다음 영상', () => {
    const v = motionContinuationView({ state: 'label' });
    expect(v.statusText).toBe('라벨 대상으로 저장됨');
    expect(v.showGtCta).toBe(true);
    expect(v.nextLabel).toBe('나중에 라벨링하고 다음 영상');
  });

  it('next busy 면 다음 버튼을 비활성화(중복 클릭 방지)', () => {
    expect(motionContinuationView({ state: 'skip', nextBusy: true }).nextDisabled).toBe(true);
    expect(motionContinuationView({ state: 'skip' }).nextDisabled).toBe(false);
  });

  it('next 실패 시 저장 성공 문구는 유지하고 재시도를 노출한다', () => {
    const v = motionContinuationView({ state: 'skip', nextFailed: true });
    expect(v.statusText).toBe('제외로 저장됨');
    expect(v.showNextRetry).toBe(true);
  });
});
