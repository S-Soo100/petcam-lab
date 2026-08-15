import { NextRequest, NextResponse } from 'next/server';
import { describe, expect, it, vi } from 'vitest';

import { createOwnerPreviewPost } from '@/lib/yoloOwnerPreviewRoute';

const jpeg = new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 0, 1]);

function previewEnv(overrides: Record<string, string | undefined> = {}) {
  return {
    VERCEL_ENV: 'preview',
    NODE_ENV: 'production',
    YOLO_V25_OWNER_PREVIEW_ENABLED: 'true',
    YOLO_V25_OWNER_WORKER_URL: 'https://yolo-v25-preview.tera-ai.uk',
    YOLO_V25_OWNER_WORKER_TOKEN: 's'.repeat(43),
    ...overrides,
  };
}

function uploadRequest(consent = 'false'): NextRequest {
  const data = new FormData();
  data.set('media', new File([jpeg], 'gecko.jpg', { type: 'image/jpeg' }));
  data.set('training_consent', consent);
  return new NextRequest('https://preview.example/api/yolo-owner/preview/infer', {
    method: 'POST',
    body: data,
  });
}

function workerFetch(overrides: Record<string, unknown> = {}) {
  return vi.fn(async (_url: string | URL | Request, init?: RequestInit) => Response.json({
    request_id: (init?.headers as Record<string, string>)['X-Request-Id'],
    media_kind: 'image',
    model_version: 'yolo26n-owner-dataset-v2.5-warm-start+2b128f105e89',
    provider_mode: 'worker',
    processed_at: '2026-08-15T08:00:00.000Z',
    warning: 'Owner Preview bbox 제안이며 GT나 학습 데이터가 아니야.',
    frames: [{ frame_index: 0, timestamp_ms: 0, detections: [] }],
    threshold: 0.20,
    development_only: true,
    usage_scope: 'owner_preview_bbox_suggestion_only',
    contribution_status: 'not_requested',
    ...overrides,
  }));
}

describe('POST /api/yolo-owner/preview/infer', () => {
  it.each([
    [401, { detail: 'unauthorized' }],
    [403, { detail: 'forbidden' }],
  ])('Owner 인증 실패 %i는 body와 worker보다 먼저 닫힌다', async (status, body) => {
    const fetchImpl = workerFetch();
    const requireOwner = vi.fn().mockResolvedValue({
      ok: false,
      response: NextResponse.json(body, { status }),
    });
    const post = createOwnerPreviewPost({
      env: previewEnv(),
      requireOwner,
      fetchImpl,
    });
    const invalidBody = new NextRequest('https://preview.example/api/yolo-owner/preview/infer', {
      method: 'POST',
      body: 'not-multipart',
    });

    const response = await post(invalidBody);

    expect(response.status).toBe(status);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('production target에서는 flag가 있어도 404이고 worker를 호출하지 않는다', async () => {
    const fetchImpl = workerFetch();
    const post = createOwnerPreviewPost({
      env: previewEnv({ VERCEL_ENV: 'production' }),
      requireOwner: vi.fn().mockResolvedValue({ ok: true, userId: 'owner-1' }),
      fetchImpl,
    });

    expect((await post(uploadRequest())).status).toBe(404);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it.each([
    ['flag off', { YOLO_V25_OWNER_PREVIEW_ENABLED: 'false' }],
    ['token missing', { YOLO_V25_OWNER_WORKER_TOKEN: undefined }],
    ['wrong origin', { YOLO_V25_OWNER_WORKER_URL: 'https://other.example' }],
  ])('%s 설정은 503 fail-closed다', async (_name, overrides) => {
    const fetchImpl = workerFetch();
    const post = createOwnerPreviewPost({
      env: previewEnv(overrides),
      requireOwner: vi.fn().mockResolvedValue({ ok: true, userId: 'owner-1' }),
      fetchImpl,
    });

    expect((await post(uploadRequest())).status).toBe(503);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('Owner Preview는 exact v2.5 identity만 반환한다', async () => {
    const fetchImpl = workerFetch();
    const post = createOwnerPreviewPost({
      env: previewEnv(),
      requireOwner: vi.fn().mockResolvedValue({ ok: true, userId: 'owner-1' }),
      fetchImpl,
    });

    const response = await post(uploadRequest());

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toMatchObject({
      model_version: 'yolo26n-owner-dataset-v2.5-warm-start+2b128f105e89',
      threshold: 0.20,
      development_only: true,
      usage_scope: 'owner_preview_bbox_suggestion_only',
      contribution_status: 'not_requested',
    });
    expect(fetchImpl).toHaveBeenCalledWith(
      'https://yolo-v25-preview.tera-ai.uk/v1/infer',
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it.each([
    ['wrong model', { model_version: 'yolo-v2.4' }],
    ['wrong threshold', { threshold: 0.25 }],
    ['wrong scope', { usage_scope: 'labeling_bbox_assist_only' }],
    ['missing development marker', { development_only: undefined }],
  ])('%s worker 응답은 502로 닫는다', async (_name, overrides) => {
    const post = createOwnerPreviewPost({
      env: previewEnv(),
      requireOwner: vi.fn().mockResolvedValue({ ok: true, userId: 'owner-1' }),
      fetchImpl: workerFetch(overrides),
    });

    expect((await post(uploadRequest())).status).toBe(502);
  });

  it('학습 제공 true는 worker 호출 전에 거부한다', async () => {
    const fetchImpl = workerFetch();
    const post = createOwnerPreviewPost({
      env: previewEnv(),
      requireOwner: vi.fn().mockResolvedValue({ ok: true, userId: 'owner-1' }),
      fetchImpl,
    });

    expect((await post(uploadRequest('true'))).status).toBe(400);
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});
