import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

import DashboardView from './_dashboard-view';

describe('팀 공용 데이터 현황', () => {
  it('영상·GT 숫자와 한국어 행동 분포를 보여준다', () => {
    const html = renderToStaticMarkup(<DashboardView data={{
      video_record_count: 20_000,
      playable_video_count: 17_702,
      gt_labeled_video_count: 2_000,
      behavior_counts: { moving: 1500, drinking: 500 },
      generated_at: '2026-07-31T10:00:00Z',
    }} />);
    expect(html).toContain('20,000');
    expect(html).toContain('17,702');
    expect(html).toContain('2,000');
    expect(html).toContain('일반 이동');
    expect(html).toContain('물 마시기');
    expect(html).not.toContain('Python Evidence');
    expect(html).not.toContain('VLM');
  });
});
