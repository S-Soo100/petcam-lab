import { describe, expect, it, vi } from 'vitest';

import { createPostFromEnv, deploymentTarget } from '@/lib/yoloDemoRoute';

import { POST } from './route';

const jpeg = new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 0, 1]);

describe('POST /api/yolo-demo/infer', () => {
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

  it('deployment target은 VERCEL_ENV를 NODE_ENV보다 우선한다', () => {
    expect(deploymentTarget({ VERCEL_ENV: 'preview', NODE_ENV: 'production' })).toBe('preview');
    expect(deploymentTarget({ VERCEL_ENV: 'production', NODE_ENV: 'test' })).toBe('production');
    expect(deploymentTarget({ NODE_ENV: 'test' })).toBe('test');
  });

  it('production은 worker env가 모두 있어도 호출하지 않고 503이다', async () => {
    const fetchImpl = vi.fn();
    const post = createPostFromEnv({
      VERCEL_ENV: 'production',
      NODE_ENV: 'production',
      YOLO_PREVIEW_ENABLED: 'true',
      YOLO_WORKER_URL: 'https://yolo-preview.example.test',
      YOLO_WORKER_TOKEN: 's'.repeat(43),
    }, fetchImpl);

    expect((await post(uploadRequest())).status).toBe(503);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('Preview는 enable/url/token이 모두 있을 때만 worker를 사용한다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(Response.json({
      request_id: expect.anything(),
    }));
    const incomplete = createPostFromEnv({ VERCEL_ENV: 'preview' }, fetchImpl);
    expect((await incomplete(uploadRequest())).status).toBe(503);
    expect(fetchImpl).not.toHaveBeenCalled();

    const workerFetch = vi.fn(async (_url: string | URL | Request, init?: RequestInit) => Response.json({
      request_id: (init?.headers as Record<string, string>)['X-Request-Id'],
      media_kind: 'image',
      model_version: 'yolo26n-owner-v2.1+9ba825697693',
      provider_mode: 'worker',
      processed_at: '2026-08-10T08:00:00.000Z',
      warning: '연구용 결과이며 오류 가능',
      frames: [{ frame_index: 0, timestamp_ms: 0, detections: [] }],
      contribution_status: 'not_requested',
    }));
    const post = createPostFromEnv({
      VERCEL_ENV: 'preview',
      NODE_ENV: 'production',
      YOLO_PREVIEW_ENABLED: 'true',
      YOLO_WORKER_URL: 'https://yolo-preview.example.test',
      YOLO_WORKER_TOKEN: 's'.repeat(43),
    }, workerFetch);

    expect((await post(uploadRequest())).status).toBe(200);
    expect(workerFetch).toHaveBeenCalledOnce();
  });
});

function uploadRequest(): Request {
  const data = new FormData();
  data.set('media', new File([jpeg], 'gecko.jpg', { type: 'image/jpeg' }));
  data.set('training_consent', 'false');
  return new Request('http://localhost/api/yolo-demo/infer', {
    method: 'POST',
    headers: { 'x-forwarded-for': '198.51.100.24' },
    body: data,
  });
}
