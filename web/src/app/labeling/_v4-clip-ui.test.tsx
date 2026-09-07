import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

// next/link 는 App Router context 를 요구하므로 테스트에선 순수 anchor 로 대체한다(_role-pages.test 와 동일).
vi.mock('next/link', () => ({
  default: ({
    href,
    className,
    children,
  }: {
    href: string;
    className?: string;
    children: React.ReactNode;
    prefetch?: boolean;
  }) => (
    <a href={href} className={className}>
      {children}
    </a>
  ),
}));

import { applyDefaultLabelState, readFilters, V4ClipCard, writeFilters } from './_v4-clip-list';
import { HighlightDecisionPanel } from './v4/_v4-clip-detail';
import { OwnerOverviewView } from './owner/_owner-overview-view';

const item = {
  id: '00000000-0000-4000-8000-000000000001',
  camera_id: 'c1',
  camera_name: '거실',
  started_at: '2026-09-08T01:00:00Z',
  duration_sec: 60,
  media_ready: true,
  highlight: {
    source: 'rule' as const,
    status: 'decided' as const,
    value: true,
    reason: '움직임 12.5초 · 최장 연속 6.0초',
    reviewer_name: null,
    decided_at: null,
  },
};

describe('V4ClipCard', () => {
  it('1차 판정 배지·근거·라벨 안 됨 표시, 상세 링크는 /labeling/v4/', () => {
    const html = renderToStaticMarkup(<V4ClipCard item={item} />);
    expect(html).toContain('하이라이트 O');
    expect(html).toContain('움직임 12.5초');
    expect(html).toContain('라벨 안 됨');
    expect(html).toContain('href="/labeling/v4/00000000-0000-4000-8000-000000000001"');
  });

  it('사람 확정이면 확정자 이름을 보여준다', () => {
    const html = renderToStaticMarkup(
      <V4ClipCard
        item={{
          ...item,
          highlight: {
            ...item.highlight,
            source: 'human',
            value: false,
            reviewer_name: '김라벨',
            decided_at: '2026-09-08T02:00:00Z',
          },
        }}
      />,
    );
    expect(html).toContain('김라벨님 확정');
    expect(html).toContain('하이라이트 X');
  });
});

describe('v4 목록 URL 필터(readFilters/writeFilters)', () => {
  const CAM = '40000000-0000-4000-8000-000000000001';
  const roundTrip = (f: Parameters<typeof writeFilters>[0]) => {
    const sp = new URLSearchParams(writeFilters(f));
    return { sp, filters: applyDefaultLabelState(sp, readFilters(sp)) };
  };

  it('labelState null 은 다른 필터가 있어도 all=1 을 남겨 기본값이 되살아나지 않는다', () => {
    const { sp, filters } = roundTrip({ cameraIds: [CAM], labelState: null, highlightState: null });
    expect(sp.get('all')).toBe('1');
    expect(sp.getAll('camera_id')).toEqual([CAM]);
    expect(filters.labelState).toBeNull();
    expect(filters.cameraIds).toEqual([CAM]);
  });

  it('필터 전부 해제도 all=1, labelState 지정 시엔 all 없이 label_state 만', () => {
    expect(writeFilters({ cameraIds: [], labelState: null, highlightState: null })).toBe('all=1');
    const { sp, filters } = roundTrip({ cameraIds: [], labelState: 'labeled', highlightState: 'yes' });
    expect(sp.has('all')).toBe(false);
    expect(filters).toEqual({ cameraIds: [], labelState: 'labeled', highlightState: 'yes' });
  });

  it('label_state 도 all 도 없는 URL 은 기본 라벨 안 됨', () => {
    const sp = new URLSearchParams(`camera_id=${CAM}`);
    expect(applyDefaultLabelState(sp, readFilters(sp)).labelState).toBe('unlabeled');
    expect(readFilters(new URLSearchParams('label_state=weird&highlight_state=maybe'))).toEqual({ cameraIds: [], labelState: null, highlightState: null });
  });
});

describe('HighlightDecisionPanel', () => {
  const initial = {
    status: 'decided' as const,
    value: true,
    rule_version: 'hl-rule-v0',
    reason: '움직임 12.5초 · 최장 연속 6.0초',
    fired: ['long_activity' as const],
    shadow: [],
    features: { activity_sec: 12.5, longest_moving_sec: 6, moving_burst_count: 2, first_moving_sec: 0.2 },
  };

  it('1차 판정과 두 확정 버튼, 1차 쪽 강조', () => {
    const html = renderToStaticMarkup(
      <HighlightDecisionPanel
        initial={initial}
        current={{
          source: 'rule',
          status: 'decided',
          value: true,
          rule_version: 'hl-rule-v0',
          reason: initial.reason,
          reviewer_name: null,
          decided_at: null,
          verdict_kind: null,
        }}
        busy={false}
        onDecide={() => {}}
      />,
    );
    expect(html).toContain('1차 판정: O');
    expect(html).toContain('O 확정');
    expect(html).toContain('X 확정');
    expect(html).toContain('오래 움직임');
  });

  it('이미 확정된 영상은 읽기 전용 문구', () => {
    const html = renderToStaticMarkup(
      <HighlightDecisionPanel
        initial={initial}
        current={{
          source: 'human',
          status: 'decided',
          value: false,
          rule_version: 'hl-rule-v0',
          reason: initial.reason,
          reviewer_name: '김라벨',
          decided_at: '2026-09-08T02:00:00Z',
          verdict_kind: 'initial',
        }}
        busy={false}
        onDecide={() => {}}
      />,
    );
    expect(html).toContain('김라벨님이 확정');
    expect(html).not.toContain('O 확정');
  });
});

describe('OwnerOverviewView (v4)', () => {
  it('집계만 보여준다', () => {
    const html = renderToStaticMarkup(
      <OwnerOverviewView
        overview={{
          activity_day: '2026-09-08',
          unlabeled_total: 120,
          labeled_today: 12,
          labeled_7d: 80,
          members: [{ user_id: '30000000-0000-4000-8000-000000000001', display_name: '김라벨', labeled_7d: 50 }],
          cameras: [{ camera_name: '거실', unlabeled: 100, labeled_7d: 60 }],
        }}
      />,
    );
    expect(html).toContain('라벨 안 된 영상');
    expect(html).toContain('120');
    expect(html).toContain('김라벨');
    expect(html).not.toContain('불일치');
  });
});
