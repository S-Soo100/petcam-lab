import { describe, expect, it } from 'vitest';

import type { GmeStateInterval } from './gmeOverlay';
import { currentSpanIndex, isPlaybackSpeed, jumpTargetSec, mergeMovingSpans, movingTotalSec, nextSpanIndex } from './movingIntervals';

const iv = (start_sec: number, end_sec: number, state: GmeStateInterval['state'] = 'moving', track = 0): GmeStateInterval => ({ start_sec, end_sec, state, track_indexes: [track] });

describe('mergeMovingSpans', () => {
  it('moving 만 모으고 0.5초 이내 끊김·track 겹침은 한 구간으로', () => {
    const spans = mergeMovingSpans([
      iv(10, 12), iv(12.3, 14, 'moving', 1), iv(11, 13, 'moving', 2), // 하나로
      iv(14.5, 15, 'static'), iv(20, 22), iv(22.6, 23), // 0.6 끊김 → 둘
      iv(5, 5, 'moving'), iv(30, 29), // 길이 0·역순은 버림
    ]);
    expect(spans).toEqual([{ start_sec: 10, end_sec: 14 }, { start_sec: 20, end_sec: 22 }, { start_sec: 22.6, end_sec: 23 }]);
    expect(movingTotalSec(spans)).toBeCloseTo(6.4);
  });
  it('구간 없으면 빈 배열', () => {
    expect(mergeMovingSpans([iv(1, 2, 'static'), iv(3, 4, 'not_visible')])).toEqual([]);
  });
});

describe('점프 대상', () => {
  const spans = mergeMovingSpans([iv(10, 12), iv(20, 22), iv(0.2, 1)]);
  it('시작 0.5초 전으로, 0 미만은 0', () => {
    expect(jumpTargetSec({ start_sec: 10, end_sec: 12 })).toBe(9.5);
    expect(jumpTargetSec({ start_sec: 0.2, end_sec: 1 })).toBe(0);
  });
  it('현재 시각 뒤 첫 구간, 끝이면 처음으로, 구간 없으면 null', () => {
    expect(nextSpanIndex(spans, 0)).toBe(1); // 0.2 구간은 "지금"(epsilon 안)이라 다음은 10
    expect(nextSpanIndex(spans, 9.6)).toBe(1);
    expect(nextSpanIndex(spans, 10)).toBe(2);
    expect(nextSpanIndex(spans, 25)).toBe(0);
    expect(nextSpanIndex([], 3)).toBeNull();
  });
  it('현재 구간 index 는 리드 구간 포함', () => {
    expect(currentSpanIndex(spans, 9.6)).toBe(1);
    expect(currentSpanIndex(spans, 12)).toBe(1);
    expect(currentSpanIndex(spans, 15)).toBe(-1);
  });
  it('속도 값 검증', () => {
    expect(isPlaybackSpeed(1.5)).toBe(true);
    expect(isPlaybackSpeed(3)).toBe(false);
  });
});
