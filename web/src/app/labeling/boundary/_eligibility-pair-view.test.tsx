import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

import EligibilityPairView from './_eligibility-pair-view';

describe('Owner 영상 자격 확인 화면', () => {
  it('다섯 자격 선택지만 보여주고 사건 판정은 숨긴다', () => {
    const html = renderToStaticMarkup(<EligibilityPairView
      pair={{
        pair_id: 'p1', ordinal: 1, gap_sec: 10, gap_bin: 'le30',
        left: { clip_id: 'l', started_at: '2026-07-01T01:00:00Z', duration_sec: 30, camera_name: '1번' },
        right: { clip_id: 'r', started_at: '2026-07-01T01:01:00Z', duration_sec: 30, camera_name: '1번' },
      }}
      urls={{ left: 'https://x/a', right: 'https://x/b' }}
      selected={null}
      submitting={false}
      onSelect={() => {}}
      onSubmit={() => {}}
    />);
    expect(html).toContain('1단계 · 영상 자격 확인');
    expect(html).toContain('둘 다 게코가 보여');
    expect(html).toContain('영상 A에 게코가 없어');
    expect(html).toContain('영상 B에 게코가 없어');
    expect(html).toContain('둘 다 게코가 없어');
    expect(html).toContain('촬영 오류 또는 화면 확인 불가');
    expect(html).toContain('판단이 어렵다는 이유만으로 무효로 고르지는 마');
    expect(html).not.toContain('같은 사건');
    expect(html).not.toContain('다른 사건');
  });
});
