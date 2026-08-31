import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { DetectionOverlay } from './_detection-overlay';
import DetectorPage from './page';
import Home from '../page';
import type { GeckoDetectionResult } from '@/lib/yoloDetection';

const base: GeckoDetectionResult = {
  request_id: 'req-1',
  media_kind: 'image',
  model_version: 'v2.6-warm-start-s28',
  provider_mode: 'worker',
  processed_at: '2026-08-10T08:00:00.000Z',
  warning: '연구용 결과이며 오류 가능',
  frames: [
    {
      frame_index: 0,
      timestamp_ms: 0,
      detections: [
        {
          label: 'gecko',
          confidence: 0.87,
          bbox: { x: 0.1, y: 0.2, width: 0.3, height: 0.4 },
        },
      ],
    },
  ],
  contribution_status: 'not_requested',
};

describe('DetectionOverlay', () => {
  it('사진 bbox와 version/confidence/처리시각/연구 경고를 함께 표시한다', () => {
    const html = renderToStaticMarkup(<DetectionOverlay result={base} mediaUrl="blob:test" />);
    expect(html).toContain('<img');
    expect(html).toContain('현재 분석 모델: YOLO v2.6');
    expect(html).toContain('v2.6-warm-start-s28');
    expect(html).toContain('87%');
    expect(html).toContain('연구용 결과이며 오류 가능');
    expect(html).toContain('2026. 8. 10.');
    expect(html).toContain('박스 숨기기');
  });

  it('v2.6 worker가 아닌 결과는 화면에 그리지 않는다', () => {
    const html = renderToStaticMarkup(
      <DetectionOverlay result={{ ...base, model_version: 'v2.5' }} mediaUrl="blob:test" />,
    );
    expect(html).not.toContain('<img');
    expect(html).not.toContain('게코 감지 박스');
  });

  it('영상 결과는 video와 frame overlay 계약을 렌더한다', () => {
    const html = renderToStaticMarkup(
      <DetectionOverlay result={{ ...base, media_kind: 'video' }} mediaUrl="blob:test-video" />,
    );
    expect(html).toContain('<video');
    expect(html).toContain('data-overlay-kind="video"');
  });
});

describe('public detector navigation', () => {
  it('공개 페이지와 루트에서 detector 진입을 제공한다', () => {
    expect(renderToStaticMarkup(<DetectorPage />)).toContain('게코 찾기 연구실');
    expect(renderToStaticMarkup(<DetectorPage />)).toContain('현재 분석 모델: YOLO v2.6');
    const home = renderToStaticMarkup(<Home />);
    expect(home).toContain('href="/gecko-detector"');
    expect(home).toContain('href="/labeling"');
  });
});
