import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import type { GmeOverlayPoint } from '@/lib/gmeOverlay';
import { GmeFeedbackReportPanel, GmeVideoOverlay } from './_gme-overlay';

const points: GmeOverlayPoint[] = [
  { track_index: 0, timestamp_sec: 1, bbox_norm: [0.1, 0.2, 0.3, 0.4], confidence: 0.9, provenance: 'observed' },
  { track_index: 0, timestamp_sec: 4, bbox_norm: [0.2, 0.2, 0.3, 0.4], confidence: 0.7, provenance: 'tracked' },
  { track_index: 1, timestamp_sec: 1.1, bbox_norm: [0.5, 0.1, 0.2, 0.2], confidence: 0.6, provenance: 'interpolated' },
];

describe('GmeVideoOverlay', () => {
  it('현재 시각에 가까운 observed와 추정 bbox만 normalized SVG로 표시한다', () => {
    const html = renderToStaticMarkup(<GmeVideoOverlay points={points} currentTimeSec={1.05} />);
    expect(html).toContain('viewBox="0 0 1 1"');
    expect(html).toContain('stroke="#22c55e"');
    expect(html).toContain('stroke="#38bdf8"');
    expect(html).toContain('stroke-width="3"');
    expect(html).toContain('stroke-dasharray="8 6"');
    expect(html).toContain('stroke-dasharray');
    expect(html.match(/<rect/g)).toHaveLength(2);
    expect(html).toContain('pointer-events-none');
  });

  it('가까운 point가 없으면 빈 SVG만 표시한다', () => {
    const html = renderToStaticMarkup(<GmeVideoOverlay points={points} currentTimeSec={20} />);
    expect(html).not.toContain('<rect');
  });
});

describe('GmeFeedbackReportPanel', () => {
  it('편향 경고와 미탐·오탐·박스 부정확 버튼을 함께 보여준다', () => {
    const html = renderToStaticMarkup(
      <GmeFeedbackReportPanel
        state="ready"
        points={points}
        currentTimeSec={1.05}
        saving={false}
        status={null}
        onReport={() => undefined}
      />,
    );
    expect(html).toContain('박스가 없어도 게코가 있을 수 있어');
    expect(html).toContain('YOLO가 게코를 놓쳤어');
    expect(html).toContain('게코가 없는데 박스가 있어');
    expect(html).toContain('게코는 있는데 박스가 틀렸어');
    expect(html).toContain('현재 1.05초');
    expect(html).not.toContain('disabled=""');
  });

  it('overlay 결과를 불러오지 못한 상태를 GME 미탐으로 표시하지 않는다', () => {
    const html = renderToStaticMarkup(
      <GmeFeedbackReportPanel
        state="unavailable"
        points={[]}
        currentTimeSec={0}
        saving={false}
        status={null}
        onReport={() => undefined}
      />,
    );
    expect(html).toContain('YOLO v2.6 결과를 확인할 수 없어. 사람 판정은 계속할 수 있어.');
    expect(html).not.toContain('영상 전체에서 YOLO v2.6 탐지 없음');
    expect(html).not.toContain('게코 없음 확인');
    expect(html.match(/disabled=""/g)).toHaveLength(3);
  });

  it('영상 전체에 point가 없을 때만 빠른 게코 없음 확인을 제공한다', () => {
    const html = renderToStaticMarkup(
      <GmeFeedbackReportPanel
        state="ready"
        points={[]}
        currentTimeSec={10}
        saving={false}
        status={null}
        onReport={() => undefined}
        onConfirmAbsent={() => undefined}
      />,
    );
    expect(html).toContain('영상 전체에서 YOLO v2.6 탐지 없음');
    expect(html).toContain('게코 없음 확인');
    expect(html).toContain('YOLO가 게코를 놓쳤어');
  });

  it('point는 있지만 현재 시각에 박스가 없으면 전체 미탐과 구분한다', () => {
    const html = renderToStaticMarkup(
      <GmeFeedbackReportPanel
        state="ready"
        points={points}
        currentTimeSec={20}
        saving={false}
        status={null}
        onReport={() => undefined}
        onConfirmAbsent={() => undefined}
      />,
    );
    expect(html).toContain('현재 시각에는 GME 박스가 없어');
    expect(html).not.toContain('영상 전체에서 YOLO v2.6 탐지 없음');
    expect(html).not.toContain('게코 없음 확인');
  });

  it('pending은 장애와 구분해 분석 대기 중으로 표시한다', () => {
    const html = renderToStaticMarkup(
      <GmeFeedbackReportPanel
        state="pending"
        points={[]}
        currentTimeSec={0}
        saving={false}
        status={null}
        onReport={() => undefined}
      />,
    );
    expect(html).toContain('YOLO v2.6 분석 대기 중');
    expect(html).not.toContain('결과를 확인할 수 없어');
    expect(html).not.toContain('영상 전체에서 YOLO v2.6 탐지 없음');
  });
});
