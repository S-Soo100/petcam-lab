import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import type { GmeStateInterval } from '@/lib/gmeOverlay';
import {
  GmeActivityOverview,
  summarizeGmeIntervals,
} from './_gme-activity-overview';

const intervals: GmeStateInterval[] = [
  { start_sec: 0, end_sec: 0.2, state: 'unknown', track_indexes: [] },
  { start_sec: 0.2, end_sec: 46.4, state: 'static', track_indexes: [0] },
  { start_sec: 46.4, end_sec: 46.5, state: 'unknown', track_indexes: [] },
  { start_sec: 46.5, end_sec: 60.8, state: 'static', track_indexes: [0] },
];

describe('summarizeGmeIntervals', () => {
  it('움직임·정지·미확정 시간을 서로 섞지 않고 합산한다', () => {
    expect(summarizeGmeIntervals(intervals, 60.8)).toEqual({
      moving_sec: 0,
      visible_sec: 60.5,
      static_sec: 60.5,
      unknown_sec: 0.3,
      camera_motion_sec: 0,
      not_visible_sec: 0,
    });
  });

  it('구간의 빈틈은 미관측으로 단정하지 않고 미확정으로 합산한다', () => {
    expect(summarizeGmeIntervals([
      { start_sec: 1, end_sec: 2, state: 'static', track_indexes: [0] },
    ], 3)).toMatchObject({
      static_sec: 1,
      unknown_sec: 2,
      not_visible_sec: 0,
    });
  });

  it('표시 정밀도에서도 움직임과 정지의 합이 보인 시간과 같다', () => {
    const summary = summarizeGmeIntervals([
      { start_sec: 0, end_sec: 0.04, state: 'moving', track_indexes: [0] },
      { start_sec: 0.04, end_sec: 0.08, state: 'static', track_indexes: [0] },
    ], 0.08);
    expect(summary.visible_sec).toBe(summary.moving_sec + summary.static_sec);
  });
});

describe('GmeActivityOverview', () => {
  it('재생 전에도 전체 시간 요약과 상태 타임라인을 표시한다', () => {
    const html = renderToStaticMarkup(
      <GmeActivityOverview
        durationSec={60.8}
        intervals={intervals}
        currentTimeSec={0}
      />,
    );

    expect(html).toContain('게코가 움직인 시간');
    expect(html).toContain('0초');
    expect(html).toContain('게코가 보인 시간');
    expect(html).toContain('60.5초');
    expect(html).toContain('게코가 정지한 시간');
    expect(html).toContain('판정 불확실');
    expect(html).toContain('0.3초');
    expect(html).toContain('전체 상태 타임라인');
    expect(html).toContain('정지 0.2–46.4초');
    expect(html).toContain('현재 위치 0초');
  });
});
