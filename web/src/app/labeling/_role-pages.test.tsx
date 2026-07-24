import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

// next/link 는 App Router context 를 요구하므로 테스트에선 순수 anchor 로 대체한다.
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

import { HistoryCard } from './_labeler-history';
import { LibraryCard, LibraryFilterControls } from './library/page';
import { LibraryDetailView } from './library/[clipId]/page';
import type { BlindHistoryItem, LabelingLibraryItem } from '@/lib/labelingRoleData';

function libraryItem(overrides: Partial<LabelingLibraryItem> = {}): LabelingLibraryItem {
  return {
    clip_id: 'clip-1',
    camera_id: 'cam-1',
    camera_name: '거실 카메라',
    started_at: '2026-07-22T10:00:00Z',
    duration_sec: 30,
    label_state: 'final',
    label_source: 'blind_consensus',
    final_decision: 'label',
    final_gt: { primary_action: 'moving' },
    ...overrides,
  };
}

function historyItem(overrides: Partial<BlindHistoryItem> = {}): BlindHistoryItem {
  return {
    submission_id: 'sub-1',
    clip_id: 'clip-1',
    camera_id: 'cam-1',
    camera_name: '거실 카메라',
    started_at: '2026-07-22T10:00:00Z',
    duration_sec: 30,
    media_ready: true,
    submitted_at: '2026-07-22T11:00:00Z',
    decision: 'label',
    reason_code: 'behavior_data',
    initial_gt: { primary_action: 'moving' },
    note: '벽 타고 이동',
    cohort_kind: 'live',
    final_status: 'confirmed',
    ...overrides,
  };
}

describe('HistoryCard — 내 기록 카드(설계 §5.2)', () => {
  it('본인 판정·사유·GT·메모·제출 시각을 보여준다', () => {
    const html = renderToStaticMarkup(<HistoryCard item={historyItem()} />);
    expect(html).toContain('라벨링'); // BLIND_DECISION_COPY.label.title
    expect(html).toContain('행동 데이터'); // reason copy
    expect(html).toContain('moving'); // 본인 GT 요약
    expect(html).toContain('벽 타고 이동'); // 본인 note
    expect(html).toContain('제출'); // 제출 시각 라벨
  });

  it('최종 상태는 확정됨/검수 중 두 단계만', () => {
    expect(renderToStaticMarkup(<HistoryCard item={historyItem({ final_status: 'confirmed' })} />)).toContain(
      '확정됨',
    );
    const inReview = renderToStaticMarkup(
      <HistoryCard item={historyItem({ final_status: 'in_review' })} />,
    );
    expect(inReview).toContain('검수 중');
  });

  it('카드 링크는 읽기 전용 영상 상세로만 간다(상대 엔드포인트 X)', () => {
    const html = renderToStaticMarkup(<HistoryCard item={historyItem()} />);
    expect(html).toContain('href="/labeling/library/clip-1"');
    expect(html).not.toContain('/labeling/blind/owner');
    expect(html).not.toContain('/api/');
  });

  it('상대 판정·digest·reviewer UUID 는 애초에 없다', () => {
    const html = renderToStaticMarkup(<HistoryCard item={historyItem()} />);
    expect(html).not.toContain('peer');
    expect(html).not.toContain('digest');
    expect(html).not.toContain('reviewer_id');
  });
});

describe('영상 보관함 필터(설계 §5.3)', () => {
  it('여섯 필터 라벨을 모두 보여준다', () => {
    const html = renderToStaticMarkup(
      <LibraryFilterControls
        value={{}}
        cameras={[{ id: 'cam-1', name: '거실 카메라' }]}
        onChange={() => {}}
        onReset={() => {}}
      />,
    );
    for (const label of ['날짜', '시간대', '카메라', '최종 라벨', '라벨 상태', '라벨 출처']) {
      expect(html).toContain(label);
    }
  });

  it('확정 전 카드는 GT/최종 판정을 보여주지 않는다(설계 §6.1)', () => {
    const awaiting = renderToStaticMarkup(
      <LibraryCard item={libraryItem({ label_state: 'awaiting', final_decision: null, final_gt: null })} />,
    );
    expect(awaiting).toContain('라벨 확정 중');
    expect(awaiting).not.toContain('최종:');
  });
});

describe('영상 보관함 상세 — 읽기 전용(설계 §5.3·§6)', () => {
  it('읽기 전용 배지 + 확정 라벨 노출, write control 없음', () => {
    const html = renderToStaticMarkup(
      <LibraryDetailView item={libraryItem()} videoUrl="https://signed/x.mp4" backHref="/labeling/library" />,
    );
    expect(html).toContain('읽기 전용');
    expect(html).toContain('최종 판정');
    for (const forbidden of ['라벨 저장', '보류하기', '제외하기', '수정하기']) {
      expect(html).not.toContain(forbidden);
    }
  });

  it('확정 전 상세는 상태 문구만, GT 없음', () => {
    const html = renderToStaticMarkup(
      <LibraryDetailView
        item={libraryItem({ label_state: 'owner_review', final_decision: null, final_gt: null })}
        videoUrl={null}
        backHref="/labeling/library"
      />,
    );
    expect(html).toContain('Owner 검수 중');
    expect(html).not.toContain('최종 판정');
  });
});
