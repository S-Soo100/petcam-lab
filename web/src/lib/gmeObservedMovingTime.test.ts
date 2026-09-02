import { describe, expect, it } from 'vitest';

import type { GmeObservedMovingTime } from './labelingV3';
import { formatGmeObservedMovingTime } from './gmeObservedMovingTime';


const IDENTITY = 'a'.repeat(64);
const RUN = '44444444-4444-4444-8444-444444444444';

function metric(
  overrides: Partial<GmeObservedMovingTime> = {},
): GmeObservedMovingTime {
  return {
    run_id: RUN,
    detector_identity: IDENTITY,
    measurement_status: 'measured',
    moving_time_sec: 18.44,
    visible_sec: 42.04,
    unknown_sec: 3.25,
    camera_motion_sec: 1,
    ...overrides,
  };
}

describe('formatGmeObservedMovingTime', () => {
  it('관측 움직임 시간은 소수 첫째 자리까지 표시한다', () => {
    expect(formatGmeObservedMovingTime(metric())).toEqual({
      title: '영상에서 확인된 움직임 18.4초',
      detail: '관측 42초 · 미확정 3.3초 · 카메라 움직임 1초',
    });
  });

  it('관측된 정지는 임의 측정불가가 아니라 정확히 0초다', () => {
    expect(
      formatGmeObservedMovingTime(metric({ moving_time_sec: 0 })).title,
    ).toBe('영상에서 확인된 움직임 0초');
  });

  it('잘못된 measured null을 관측된 정지 0초로 바꾸지 않는다', () => {
    expect(
      formatGmeObservedMovingTime(metric({ moving_time_sec: null })),
    ).toEqual({
      title: 'GME 분석 실패',
      detail: '현재 모델의 결과가 올바르지 않아 움직임 시간을 표시할 수 없어.',
    });
  });

  it('미관측·대기·실패를 서로 다른 문구로 표시한다', () => {
    expect(
      formatGmeObservedMovingTime(
        metric({
          measurement_status: 'not_observed',
          moving_time_sec: null,
          visible_sec: 0,
        }),
      ),
    ).toEqual({
      title: '게코 미관측 · 측정 불가',
      detail: '관측 0초 · 미확정 3.3초 · 카메라 움직임 1초',
    });

    expect(
      formatGmeObservedMovingTime(
        metric({
          run_id: null,
          measurement_status: 'pending',
          moving_time_sec: null,
          visible_sec: null,
          unknown_sec: null,
          camera_motion_sec: null,
        }),
      ),
    ).toEqual({
      title: 'GME 분석 대기 중',
      detail: '현재 모델의 분석이 끝나면 관측 움직임 시간을 표시해.',
    });

    expect(
      formatGmeObservedMovingTime(
        metric({
          run_id: null,
          measurement_status: 'failed',
          moving_time_sec: null,
          visible_sec: null,
          unknown_sec: null,
          camera_motion_sec: null,
        }),
      ),
    ).toEqual({
      title: 'GME 분석 실패',
      detail: '현재 모델의 결과가 없어 움직임 시간을 표시할 수 없어.',
    });
  });
});
