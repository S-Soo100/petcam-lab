import { describe, expect, it } from 'vitest';

import { createProductionDependencies } from '@/lib/yoloProductionDependencies';

import * as routeModule from './route';

const { POST } = routeModule;

const jpeg = new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 0, 1]);

describe('POST /api/yolo-demo/infer', () => {
  it('Next.js가 허용한 route export만 노출한다', () => {
    expect(Object.keys(routeModule).sort()).toEqual(['POST', 'maxDuration', 'runtime']);
  });

  it('실제 multipart 요청을 versioned detection DTO로 바꾼다', async () => {
    const data = new FormData();
    data.set('media', new File([jpeg], 'gecko.jpg', { type: 'image/jpeg' }));
    data.set('training_consent', 'true');
    const response = await POST(
      new Request('http://localhost/api/yolo-demo/infer', {
        method: 'POST',
        headers: { 'x-forwarded-for': '198.51.100.24' },
        body: data,
      }),
    );

    expect(response.status).toBe(200);
    expect(response.headers.get('cache-control')).toBe('no-store');
    await expect(response.json()).resolves.toMatchObject({
      media_kind: 'image',
      model_version: 'fake-yolo-v0',
      provider_mode: 'fake',
      contribution_status: 'candidate_only',
    });
  });

  it('production은 네 실행 계약이 모두 맞아야 actual worker를 구성한다', () => {
    const complete = {
      YOLO_WORKER_URL: 'https://worker.example/v1/infer',
      YOLO_WORKER_TOKEN: 'worker-token',
      YOLO_RATE_LIMIT_HMAC_SECRET: 's'.repeat(32),
      GME_ACTIVE_DETECTOR_IDENTITY: 'deccfc8315d3c00edb5bf59db3c573dca568e9d6d7a5da8d7dc93d2082bdb899',
    };
    expect(createProductionDependencies(complete)).toMatchObject({
      provider: { mode: 'worker' }, limiter: { scope: 'distributed' }, environment: 'production',
    });
    expect(createProductionDependencies({ ...complete, YOLO_WORKER_TOKEN: '' })).toBeNull();
    expect(createProductionDependencies({
      ...complete, GME_ACTIVE_DETECTOR_IDENTITY: 'd4654168af21d26697ab1bd9a5dc4a05bd92baf5c9328800915cc347803d05b6',
    })).toBeNull();
  });
});
