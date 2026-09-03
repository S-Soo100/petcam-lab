import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import type { GmeOverlayPoint } from '@/lib/gmeOverlay';
import { GmeFeedbackReportPanel, GmeVideoOverlay } from './_gme-overlay';

const points: GmeOverlayPoint[] = [
  { track_index: 0, timestamp_sec: 1, bbox_norm: [0.1, 0.2, 0.3, 0.4], confidence: 0.9, provenance: 'observed' },
  { track_index: 0, timestamp_sec: 4, bbox_norm: [0.2, 0.2, 0.3, 0.4], confidence: 0.7, provenance: 'tracked' },
  { track_index: 1, timestamp_sec: 1.1, bbox_norm: [0.5, 0.1, 0.2, 0.2], confidence: 0.6, provenance: 'interpolated' },
];
const intervals = [
  { start_sec: 0, end_sec: 2, state: 'static' as const, track_indexes: [0] },
  { start_sec: 2, end_sec: 5, state: 'moving' as const, track_indexes: [0] },
];

describe('GmeVideoOverlay', () => {
  it('정지 구간은 provenance와 무관하게 회색 박스로 표시한다', () => {
    const html = renderToStaticMarkup(
      <GmeVideoOverlay points={points} intervals={intervals} currentTimeSec={1.05} />,
    );
    expect(html).toContain('viewBox="0 0 1 1"');
    expect(html).toContain('stroke="#94a3b8"');
    expect(html).toContain('stroke="#f59e0b"');
    expect(html).not.toContain('stroke="#22c55e"');
    expect(html).toContain('stroke-width="3"');
    expect(html).toContain('stroke-dasharray="8 6"');
    expect(html).toContain('stroke-dasharray');
    expect(html.match(/<rect/g)).toHaveLength(2);
    expect(html).toContain('pointer-events-none');
  });

  it('움직임 구간만 초록색 박스로 표시한다', () => {
    const html = renderToStaticMarkup(
      <GmeVideoOverlay points={points} intervals={intervals} currentTimeSec={4} />,
    );
    expect(html).toContain('stroke="#22c55e"');
  });

  it('가까운 point가 없으면 빈 SVG만 표시한다', () => {
    const html = renderToStaticMarkup(
      <GmeVideoOverlay points={points} intervals={intervals} currentTimeSec={20} />,
    );
    expect(html).not.toContain('<rect');
  });
});

describe('GmeFeedbackReportPanel', () => {
  it('blind 화면에는 기존 박스 안내와 미탐·오탐·박스 부정확 버튼을 보여준다', () => {
    const html = renderToStaticMarkup(
      <GmeFeedbackReportPanel
        available
        points={points}
        currentTimeSec={1.05}
        saving={false}
        status={null}
        onReport={() => undefined}
      />,
    );
    expect(html).toContain('박스가 없어도 게코가 있을 수 있어');
    expect(html).not.toContain('회색은 정지');
    expect(html).toContain('YOLO가 게코를 놓쳤어');
    expect(html).toContain('게코가 없는데 박스가 있어');
    expect(html).toContain('게코는 있는데 박스가 틀렸어');
    expect(html).toContain('현재 1.05초');
    expect(html).not.toContain('disabled=""');
  });

  it('상태 구간을 쓰는 Owner 화면에서만 상태별 색을 안내한다', () => {
    const html = renderToStaticMarkup(
      <GmeFeedbackReportPanel
        available
        stateAware
        points={points}
        currentTimeSec={1.05}
        saving={false}
        status={null}
        onReport={() => undefined}
      />,
    );
    expect(html).toContain('회색은 정지, 초록은 움직임, 노랑은 미확정');
  });

  it('overlay 결과를 불러오지 못한 상태를 GME 미탐으로 표시하지 않는다', () => {
    const html = renderToStaticMarkup(
      <GmeFeedbackReportPanel
        available={false}
        points={[]}
        currentTimeSec={0}
        saving={false}
        status={null}
        onReport={() => undefined}
      />,
    );
    expect(html).toContain('GME 결과를 확인할 수 없어');
    expect(html).not.toContain('영상 전체에서 GME 탐지 없음');
    expect(html).not.toContain('게코 없음 확인');
    expect(html.match(/disabled=""/g)).toHaveLength(3);
  });

  it('영상 전체에 point가 없을 때만 빠른 게코 없음 확인을 제공한다', () => {
    const html = renderToStaticMarkup(
      <GmeFeedbackReportPanel
        available
        points={[]}
        currentTimeSec={10}
        saving={false}
        status={null}
        onReport={() => undefined}
        onConfirmAbsent={() => undefined}
      />,
    );
    expect(html).toContain('영상 전체에서 GME 탐지 없음');
    expect(html).toContain('게코 없음 확인');
    expect(html).toContain('YOLO가 게코를 놓쳤어');
  });

  it('point는 있지만 현재 시각에 박스가 없으면 전체 미탐과 구분한다', () => {
    const html = renderToStaticMarkup(
      <GmeFeedbackReportPanel
        available
        points={points}
        currentTimeSec={20}
        saving={false}
        status={null}
        onReport={() => undefined}
        onConfirmAbsent={() => undefined}
      />,
    );
    expect(html).toContain('현재 시각에는 GME 박스가 없어');
    expect(html).not.toContain('영상 전체에서 GME 탐지 없음');
    expect(html).not.toContain('게코 없음 확인');
  });
});
