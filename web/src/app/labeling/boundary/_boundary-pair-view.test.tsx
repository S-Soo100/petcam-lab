import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

import BoundaryPairView from './_boundary-pair-view';

describe('사건 경계 문제 화면', () => {
  it('A→B 영상과 세 판정만 보여주고 상대 답은 보이지 않는다', () => {
    const html = renderToStaticMarkup(<BoundaryPairView
      pair={{
        pair_id: 'p1', ordinal: 4, gap_sec: 29.4, gap_bin: 'le30',
        left: { clip_id: 'l', started_at: '2026-07-01T01:00:00Z', duration_sec: 30, camera_name: '1번' },
        right: { clip_id: 'r', started_at: '2026-07-01T01:01:00Z', duration_sec: 30, camera_name: '1번' },
      }}
      urls={{ left: 'https://x/a', right: 'https://x/b' }}
      selected={null}
      submitting={false}
      onSelect={() => {}}
      onSubmit={() => {}}
    />);
    expect(html).toContain('1/2 · 영상 A');
    expect(html).toContain('2/2 · 영상 B');
    expect(html).toContain('같은 사건');
    expect(html).toContain('다른 사건');
    expect(html).toContain('잘 모르겠음');
    expect(html).not.toContain('상대 답');
    expect(html).not.toContain('행동 라벨');
  });
});
