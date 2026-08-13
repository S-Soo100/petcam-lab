import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { DetectionOverlay } from './_detection-overlay';
import DetectorPage from './page';
import Home from '../page';
import type { GeckoDetectionResult } from '@/lib/yoloDetection';

const base: GeckoDetectionResult = {
  request_id: 'req-1',
  media_kind: 'image',
  model_version: 'fake-yolo-v0',
  provider_mode: 'fake',
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
    expect(html).toContain('fake-yolo-v0');
    expect(html).toContain('87%');
    expect(html).toContain('연구용 결과이며 오류 가능');
    expect(html).toContain('2026. 8. 10.');
    expect(html).toContain('박스 숨기기');
  });

  it('non-scaling bbox 선은 화면에서 보이는 1px 이상으로 렌더한다', () => {
    const html = renderToStaticMarkup(<DetectionOverlay result={base} mediaUrl="blob:test" />);
    const strokeWidth = html.match(/stroke-width="([^"]+)"/)?.[1];

    expect(Number(strokeWidth)).toBeGreaterThanOrEqual(1);
    expect(html).toContain('vector-effect="non-scaling-stroke"');
  });

  it('영상 결과는 video와 frame overlay 계약을 렌더한다', () => {
    const html = renderToStaticMarkup(
      <DetectionOverlay result={{ ...base, media_kind: 'video' }} mediaUrl="blob:test-video" />,
    );
    expect(html).toContain('<video');
    expect(html).toContain('data-overlay-kind="video"');
  });

  it('v2.3 assist 결과에서만 실제 threshold와 scope를 표시한다', () => {
    const html = renderToStaticMarkup(
      <DetectionOverlay
        result={{
          ...base,
          provider_mode: 'worker',
          model_version: 'yolo26n-owner-dataset-v2.3-warm-start+dbed3a2d8018',
          threshold: 0.25,
          development_only: true,
          usage_scope: 'labeling_bbox_assist_only',
        }}
        mediaUrl="blob:test"
      />,
    );
    expect(html).toContain('threshold 0.25');
    expect(html).toContain('development-only 라벨링 보조');
  });

  it('v2.1 rollback 결과를 v2.3으로 오표시하지 않는다', () => {
    const html = renderToStaticMarkup(
      <DetectionOverlay
        result={{ ...base, provider_mode: 'worker', model_version: 'yolo26n-owner-v2.1+9ba825697693' }}
        mediaUrl="blob:test"
      />,
    );
    expect(html).toContain('yolo26n-owner-v2.1+9ba825697693');
    expect(html).not.toContain('v2.3');
    expect(html).not.toContain('threshold 0.25');
  });
});

describe('public detector navigation', () => {
  it('공개 페이지와 루트에서 detector 진입을 제공한다', () => {
    expect(renderToStaticMarkup(<DetectorPage />)).toContain('게코 찾기 연구실');
    const home = renderToStaticMarkup(<Home />);
    expect(home).toContain('href="/gecko-detector"');
    expect(home).toContain('href="/labeling"');
  });
});
