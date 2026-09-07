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

import { LibraryCard, LibraryFilterControls } from './library/_library-views';
import { LibraryDetailView } from './library/[clipId]/_library-detail-view';
import type { LabelingLibraryItem } from '@/lib/labelingRoleData';

// 이중 blind 내 기록·Canary·구 Owner 운영 현황 테스트는 2026-09-08 트랙 퇴역과 함께 제거.
// v4 운영 현황(OwnerOverviewView)·목록 카드·확정 패널 계약은 `_v4-clip-ui.test.tsx`.

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
      <LibraryDetailView item={libraryItem()} videoUrl="https://signed/x.mp4" backHref="/labeling/library"
        getDownload={async () => ({ url: 'https://download/x.mp4', filename: 'x.mp4' })} />,
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
        getDownload={async () => ({ url: 'https://download/x.mp4', filename: 'x.mp4' })}
      />,
    );
    expect(html).toContain('Owner 검수 중');
    expect(html).not.toContain('최종 판정');
  });
});
