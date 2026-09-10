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

import { applyDefaultLabelState, ProgressRow, readFilters, V4ClipCard, writeFilters } from './_v4-clip-list';
import { parseProgress } from '@/lib/labelingV4Progress';
import { BehaviorFlagButton, HighlightDecisionPanel, MotionNavRow, O_TO_X_REASONS, V4ClipLoading, needsChangeReason } from './v4/_v4-clip-detail';
import { HIGHLIGHT_CHANGE_REASON_DESCRIPTIONS, HIGHLIGHT_CHANGE_REASON_LABELS, isGeckoNotObserved } from '@/lib/highlightV4';
import { CoverageLine, OwnerOverviewView } from './owner/_owner-overview-view';

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
  behavior_flag: { flagged: false, flagged_by_name: null, flagged_at: null },
  thumbnail_url: null,
  featured: null,
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

describe('ProgressRow (이어서 라벨링)', () => {
  it('진행 문구 + CTA, 로딩 중 문구, 찾는 중 잠금', () => {
    const p = parseProgress({ labeled_today_me: 7, unlabeled_all: 120, unlabeled_mine: 30 });
    const html = renderToStaticMarkup(<ProgressRow progress={p} scope="mine" busy={false} onContinue={() => {}} />);
    expect(html).toContain('오늘 내가 7개 · 남은 30개');
    expect(html).toContain('이어서 라벨링');
    expect(renderToStaticMarkup(<ProgressRow progress={null} scope="all" busy onContinue={() => {}} />)).toContain('찾는 중');
  });
  it('상세 바에 진행 문구가 오른쪽에 붙는다', () => {
    const html = renderToStaticMarkup(
      <HighlightDecisionPanel
        initial={{ status: 'decided', value: true, rule_version: 'hl-rule-v0', reason: '움직임 12.5초', fired: ['long_activity'], shadow: [], features: null }}
        current={{ source: 'rule', status: 'decided', value: true, rule_version: 'hl-rule-v0', reason: '움직임 12.5초', reviewer_name: null, decided_at: null, verdict_kind: null }}
        busy={false}
        onDecide={() => {}}
        progressText="오늘 3 · 남은 99"
      />,
    );
    expect(html).toContain('data-testid="progress-text"');
    expect(html).toContain('오늘 3 · 남은 99');
  });
});

describe('MotionNavRow (움직임 내비)', () => {
  const spans = [{ start_sec: 10, end_sec: 14 }, { start_sec: 30, end_sec: 33 }];
  const base = { speed: 1 as const, autoSkip: true, skipNote: null, onJump: () => {}, onSpeed: () => {}, onToggleAutoSkip: () => {} };
  it('구간 요약·다음 움직임·속도·움직임부터 시작', () => {
    const html = renderToStaticMarkup(<MotionNavRow spans={spans} currentSec={0} {...base} />);
    expect(html).toContain('움직임 2구간 · 7.0초');
    expect(html).toContain('다음 움직임 1/2');
    expect(html).toContain('1.5×');
    expect(html).toContain('움직임부터 시작');
  });
  it('마지막 구간 뒤에선 처음으로 되감기, 구간 안에선 지금 n/m', () => {
    expect(renderToStaticMarkup(<MotionNavRow spans={spans} currentSec={40} {...base} />)).toContain('처음 움직임으로');
    expect(renderToStaticMarkup(<MotionNavRow spans={spans} currentSec={11} {...base} />)).toContain('지금 1/2');
  });
  it('구간 없으면 GME 상태별 문구(대기/미관측/정지), 점프 버튼 없음', () => {
    const empty = (extra: Partial<Parameters<typeof MotionNavRow>[0]>) => renderToStaticMarkup(<MotionNavRow spans={[]} currentSec={0} {...base} skipNote="x" {...extra} />);
    expect(empty({ gmeState: 'missing' })).toContain('GME 분석 대기');
    expect(empty({ gmeState: 'loading' })).toContain('불러오는 중');
    expect(empty({ gmeState: 'ready', notObserved: true })).toContain('게코 미관측');
    expect(empty({ gmeState: 'ready' })).toContain('움직임 없음(정지)');
    expect(empty({})).not.toContain('다음 움직임');
  });
});

describe('의미있는 행동 체크', () => {
  it('카드는 체크된 영상에만 배지', () => {
    expect(renderToStaticMarkup(<V4ClipCard item={item} />)).not.toContain('의미있는 행동');
    const html = renderToStaticMarkup(<V4ClipCard item={{ ...item, behavior_flag: { flagged: true, flagged_by_name: '김라벨', flagged_at: '2026-09-08T04:00:00Z' } }} />);
    expect(html).toContain('의미있는 행동');
  });
  it('행동 라벨링 링크는 owner(gtHref)이면서 체크된 영상에만', () => {
    const flagged = { ...item, behavior_flag: { flagged: true, flagged_by_name: '김라벨', flagged_at: '2026-09-08T04:00:00Z' } };
    const href = `/labeling/motion/${item.id}`;
    expect(renderToStaticMarkup(<V4ClipCard item={flagged} gtHref={href} />)).toContain(`href="${href}"`);
    expect(renderToStaticMarkup(<V4ClipCard item={flagged} />)).not.toContain('행동 라벨링');
    expect(renderToStaticMarkup(<V4ClipCard item={item} gtHref={href} />)).not.toContain('행동 라벨링');
    const on = renderToStaticMarkup(<BehaviorFlagButton flag={flagged.behavior_flag} busy={false} onToggle={() => {}} gtHref={href} />);
    expect(on).toContain('행동 라벨링 열기');
    expect(renderToStaticMarkup(<BehaviorFlagButton flag={item.behavior_flag} busy={false} onToggle={() => {}} gtHref={href} />)).not.toContain('행동 라벨링');
  });

  it('버튼은 체크 상태·체크한 사람·저장 중을 구분한다', () => {
    const off = renderToStaticMarkup(<BehaviorFlagButton flag={{ flagged: false, flagged_by_name: null, flagged_at: null }} busy={false} onToggle={() => {}} />);
    expect(off).toContain('aria-pressed="false"');
    expect(off).toContain('의미있는 행동 보여');
    const on = renderToStaticMarkup(<BehaviorFlagButton flag={{ flagged: true, flagged_by_name: '김라벨', flagged_at: null }} busy={false} onToggle={() => {}} />);
    expect(on).toContain('aria-pressed="true"');
    expect(on).toContain('체크됨 · 김라벨');
    expect(renderToStaticMarkup(<BehaviorFlagButton flag={{ flagged: false, flagged_by_name: null, flagged_at: null }} busy onToggle={() => {}} />)).toContain('저장 중');
  });
  it('URL 필터 sample=<id> 왕복, 잘못된 형식은 무시', () => {
    const sp = new URLSearchParams(writeFilters({ cameraIds: [], labelState: 'unlabeled', highlightState: null, behaviorFlag: null, sampleId: 'eval-2026-09' }));
    expect(sp.get('sample')).toBe('eval-2026-09');
    expect(readFilters(sp).sampleId).toBe('eval-2026-09');
    expect(readFilters(new URLSearchParams('sample=BAD%20id')).sampleId).toBeNull();
    expect(renderToStaticMarkup(<ProgressRow progress={null} scope="all" busy={false} sampleProgress={{ sample_id: 'eval-2026-09', total: 100, labeled: 57 }} onContinue={() => {}} />)).toContain('표본 57/100 확정');
  });
  it('URL 필터 behavior_flag=yes 왕복', () => {
    const sp = new URLSearchParams(writeFilters({ cameraIds: [], labelState: 'unlabeled', highlightState: null, behaviorFlag: 'yes', sampleId: null }));
    expect(sp.get('behavior_flag')).toBe('yes');
    expect(readFilters(sp).behaviorFlag).toBe('yes');
    expect(readFilters(new URLSearchParams('behavior_flag=no')).behaviorFlag).toBeNull();
  });
});

describe('v4 목록 URL 필터(readFilters/writeFilters)', () => {
  const CAM = '40000000-0000-4000-8000-000000000001';
  const roundTrip = (f: Parameters<typeof writeFilters>[0]) => {
    const sp = new URLSearchParams(writeFilters(f));
    return { sp, filters: applyDefaultLabelState(sp, readFilters(sp)) };
  };

  it('labelState null 은 다른 필터가 있어도 all=1 을 남겨 기본값이 되살아나지 않는다', () => {
    const { sp, filters } = roundTrip({ cameraIds: [CAM], labelState: null, highlightState: null, behaviorFlag: null, sampleId: null });
    expect(sp.get('all')).toBe('1');
    expect(sp.getAll('camera_id')).toEqual([CAM]);
    expect(filters.labelState).toBeNull();
    expect(filters.cameraIds).toEqual([CAM]);
  });

  it('필터 전부 해제도 all=1, labelState 지정 시엔 all 없이 label_state 만', () => {
    expect(writeFilters({ cameraIds: [], labelState: null, highlightState: null, behaviorFlag: null, sampleId: null })).toBe('all=1');
    const { sp, filters } = roundTrip({ cameraIds: [], labelState: 'labeled', highlightState: 'yes', behaviorFlag: null, sampleId: null });
    expect(sp.has('all')).toBe(false);
    expect(filters).toEqual({ cameraIds: [], labelState: 'labeled', highlightState: 'yes', behaviorFlag: null, sampleId: null });
  });

  it('label_state 도 all 도 없는 URL 은 기본 라벨 안 됨', () => {
    const sp = new URLSearchParams(`camera_id=${CAM}`);
    expect(applyDefaultLabelState(sp, readFilters(sp)).labelState).toBe('unlabeled');
    expect(readFilters(new URLSearchParams('label_state=weird&highlight_state=maybe'))).toEqual({ cameraIds: [], labelState: null, highlightState: null, behaviorFlag: null, sampleId: null });
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
    features: { activity_sec: 12.5, longest_moving_sec: 6, moving_burst_count: 2, first_moving_sec: 0.2, visible_sec: 58 },
  };

  it('모바일 액션 바: 하단 고정 + 1차 요약 한 줄 + 엄지용 큰 버튼, lg 에선 정적', () => {
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
    expect(html).toContain('data-testid="highlight-action-bar"');
    expect(html).toContain('fixed inset-x-0 bottom-0');
    expect(html).toContain('lg:static');
    expect(html).toContain('safe-area-inset-bottom');
    expect(html).toContain('1차 O · 움직임 12.5초');
    expect(html).toContain('min-h-14');
    expect(html).toContain('touch-manipulation');
  });

  it('저장 중(busy)엔 진행 문구가 보이고 버튼은 잠긴다', () => {
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
        busy
        onDecide={() => {}}
      />,
    );
    expect(html).toContain('저장하고 다음 영상으로 넘어가는 중…');
    expect(html).toContain('aria-live="polite"');
    expect(html).toContain('aria-busy="true"');
    expect(html).toContain('disabled=""');
  });

  it('로딩 화면도 같은 액션 바 자리에 스피너와 문구', () => {
    const html = renderToStaticMarkup(<V4ClipLoading message="다음 영상 불러오는 중…" />);
    expect(html).toContain('다음 영상 불러오는 중…');
    expect(html).toContain('animate-spin');
    expect(html).toContain('fixed inset-x-0 bottom-0');
  });

  it('게코 미관측 1차 판정은 O/X 대신 안 보여/보여 세 버튼', () => {
    const notObserved = { ...initial, value: false, reason: '게코 미관측', fired: [], features: { ...initial.features, visible_sec: 0 } };
    expect(isGeckoNotObserved(notObserved)).toBe(true);
    expect(isGeckoNotObserved({ ...notObserved, features: null })).toBe(true);
    expect(isGeckoNotObserved({ ...notObserved, features: null, reason: '짧은 움직임 3.0초' })).toBe(false);
    expect(isGeckoNotObserved(initial)).toBe(false);
    const html = renderToStaticMarkup(
      <HighlightDecisionPanel
        initial={notObserved}
        current={{ source: 'rule', status: 'decided', value: false, rule_version: 'hl-rule-v0', reason: '게코 미관측', reviewer_name: null, decided_at: null, verdict_kind: null }}
        busy={false}
        onDecide={() => {}}
      />,
    );
    expect(html).toContain('게코 안 보여 · X 확정');
    expect(html).toContain('게코 보여 · 하이라이트 O');
    expect(html).toContain('게코 보여 · 하이라이트 아님 X');
    expect(html).not.toContain('>O 확정<');
    expect(html).toContain('1차 판정: X (게코 미관측)');
  });

  it('썸네일 URL 이 있으면 카드에 lazy img', () => {
    const html = renderToStaticMarkup(<V4ClipCard item={{ ...item, thumbnail_url: 'https://r2.example/t.jpg' }} />);
    expect(html).toContain('src="https://r2.example/t.jpg"');
    expect(html).toContain('loading="lazy"');
    expect(renderToStaticMarkup(<V4ClipCard item={item} />)).not.toContain('<img');
  });

  it('사유 칩마다 설명이 있고 라벨은 움직임 짧음', () => {
    expect(HIGHLIGHT_CHANGE_REASON_LABELS.too_short).toBe('움직임 짧음');
    expect(HIGHLIGHT_CHANGE_REASON_LABELS.gecko_visible_not_highlight).toBe('게코 보여·하이라이트 아님');
    expect(O_TO_X_REASONS).not.toContain('gecko_visible_not_highlight');
    for (const r of O_TO_X_REASONS) expect(HIGHLIGHT_CHANGE_REASON_DESCRIPTIONS[r].length).toBeGreaterThan(5);
  });

  it('사유는 규칙 O→사람 X 만 묻고, X→O·같은 판정·1차 없음은 즉시 저장', () => {
    expect(needsChangeReason({ status: 'decided', value: true }, false)).toBe(true);
    expect(needsChangeReason({ status: 'decided', value: true }, true)).toBe(false);
    expect(needsChangeReason({ status: 'decided', value: false }, true)).toBe(false);
    expect(needsChangeReason({ status: 'decided', value: false }, false)).toBe(false);
    expect(needsChangeReason({ status: 'pending', value: null }, false)).toBe(false);
    expect(O_TO_X_REASONS).not.toContain('interesting_low_numbers');
    expect(O_TO_X_REASONS).toHaveLength(5);
  });

  it('확정된 영상에 onNext 가 있으면 액션 바에 다음 버튼', () => {
    const html = renderToStaticMarkup(
      <HighlightDecisionPanel
        initial={initial}
        current={{
          source: 'human',
          status: 'decided',
          value: true,
          rule_version: 'hl-rule-v0',
          reason: initial.reason,
          reviewer_name: '김라벨',
          decided_at: '2026-09-08T02:00:00Z',
          verdict_kind: 'initial',
        }}
        busy={false}
        onDecide={() => {}}
        onNext={() => {}}
      />,
    );
    expect(html).toContain('다음 안 된 영상');
    expect(html).not.toContain('O 확정');
  });

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

describe('CoverageLine', () => {
  it('null 이면 집계 실패 문구, 분모 0 이면 -', () => {
    expect(renderToStaticMarkup(<CoverageLine coverage={null} />)).toContain('집계 못 가져옴');
    expect(renderToStaticMarkup(<CoverageLine coverage={{ last7d_total: 0, last7d_with_run: 0, all_total: 10, all_with_run: 5 }} />)).toContain('최근 7일 - (0/0)');
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
          coverage: { last7d_total: 1006, last7d_with_run: 1006, all_total: 26761, all_with_run: 12530 },
        }}
      />,
    );
    expect(html).toContain('최근 7일 100% (1,006/1,006)');
    expect(html).toContain('전체 47% (12,530/26,761)');
    expect(html).toContain('라벨 안 된 영상');
    expect(html).toContain('120');
    expect(html).toContain('김라벨');
    expect(html).not.toContain('불일치');
  });
});
