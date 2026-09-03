import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import type { GmeObservedMovingTime } from '@/lib/labelingV3';
import GmeObservedMovingTimeCard from './_gme-observed-moving-time-card';


const IDENTITY = 'a'.repeat(64);

function metric(
  overrides: Partial<GmeObservedMovingTime> = {},
): GmeObservedMovingTime {
  return {
    run_id: '44444444-4444-4444-8444-444444444444',
    detector_identity: IDENTITY,
    measurement_status: 'measured',
    moving_time_sec: 18.4,
    visible_sec: 42,
    unknown_sec: 3,
    camera_motion_sec: 1,
    ...overrides,
  };
}

describe('GmeObservedMovingTimeCard', () => {
  it('관측 움직임 시간과 근거 초를 표시하되 provenance는 노출하지 않는다', () => {
    const html = renderToStaticMarkup(
      <GmeObservedMovingTimeCard metric={metric()} />,
    );
    expect(html).toContain('GME 관측 움직임 시간');
    expect(html).toContain('영상에서 확인된 움직임 18.4초');
    expect(html).toContain('게코가 보인 시간 42초');
    expect(html).toContain('행동 정답이나 건강 진단이 아니야');
    expect(html).not.toContain(IDENTITY);
    expect(html).not.toContain('44444444-4444-4444-8444-444444444444');
  });

  it('pending 상태는 임의의 0초 대신 대기 문구를 표시한다', () => {
    const html = renderToStaticMarkup(
      <GmeObservedMovingTimeCard
        metric={metric({
          run_id: null,
          measurement_status: 'pending',
          moving_time_sec: null,
          visible_sec: null,
          unknown_sec: null,
          camera_motion_sec: null,
        })}
      />,
    );
    expect(html).toContain('GME 분석 대기 중');
    expect(html).not.toContain('확인된 움직임 0초');
  });
});
