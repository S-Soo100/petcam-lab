import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

import {
  OwnerYoloV25Preview,
  requestOwnerYoloPreview,
} from './_owner-yolo-v25-preview';

describe('OwnerYoloV25Preview', () => {
  it('Preview 상태·고정 모델·threshold·future holdout 경계를 항상 표시한다', () => {
    const html = renderToStaticMarkup(<OwnerYoloV25Preview />);

    expect(html).toContain('Owner Preview');
    expect(html).toContain('Development-only');
    expect(html).toContain('v2.5 warm-start');
    expect(html).toContain('threshold 0.20');
    expect(html).toContain('future holdout');
    expect(html).toContain('GT가 아니야');
    expect(html).not.toContain('Dataset 승인');
    expect(html).not.toContain('모델 활성화');
    expect(html).not.toContain('학습 데이터 후보로 제공');
  });

  it('요청은 Owner bearer와 training_consent=false만 전송한다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(Response.json({
      request_id: 'request-1',
      media_kind: 'image',
      model_version: 'yolo26n-owner-dataset-v2.5-warm-start+2b128f105e89',
      provider_mode: 'worker',
      processed_at: '2026-08-15T08:00:00.000Z',
      warning: 'Owner Preview bbox 제안이며 GT가 아니야.',
      frames: [{ frame_index: 0, timestamp_ms: 0, detections: [] }],
      threshold: 0.20,
      development_only: true,
      usage_scope: 'owner_preview_bbox_suggestion_only',
      contribution_status: 'not_requested',
    }));
    const file = new File(
      [new Uint8Array([0xff, 0xd8, 0xff])],
      'gecko.jpg',
      { type: 'image/jpeg' },
    );

    await requestOwnerYoloPreview(file, 'owner-token', fetchImpl);

    const [, init] = fetchImpl.mock.calls[0] as [string, RequestInit];
    expect(fetchImpl).toHaveBeenCalledWith(
      '/api/yolo-owner/preview/infer',
      expect.objectContaining({ method: 'POST' }),
    );
    expect(init.headers).toEqual({ Authorization: 'Bearer owner-token' });
    const body = init.body as FormData;
    expect(body.get('media')).toBe(file);
    expect(body.get('training_consent')).toBe('false');
  });
});
