import { describe, expect, it, vi } from 'vitest';

import { DetectionInputRejectedError, type DetectionInput } from './yoloDetectionServer';
import { HttpGeckoDetectionProvider } from './yoloHttpProvider';

const input: DetectionInput = {
  requestId: '00000000-0000-4000-8000-000000000001',
  bytes: new Uint8Array([0xff, 0xd8, 0xff, 0xe0]),
  mediaKind: 'image',
  contentType: 'image/jpeg',
  originalSize: 4,
  trainingConsent: false,
  limits: {
    decodeTimeoutMs: 15_000,
    imageMaxPixels: 20_000_000,
    maxVideoDurationMs: 60_000,
    maxVideoFps: 30,
    maxVideoWidth: 1920,
    maxVideoHeight: 1080,
    temporaryStorageTtlSec: 900,
  },
};

const workerResult = {
  request_id: input.requestId,
  media_kind: 'image',
  model_version: 'yolo26n-owner-dataset-v2.3-warm-start+dbed3a2d8018',
  provider_mode: 'worker',
  processed_at: '2026-08-10T08:00:00.000Z',
  warning: '라벨링 보조 후보야. 박스가 없어도 게코 없음 판정이 아니야.',
  frames: [],
  contribution_status: 'not_requested',
};

describe('HttpGeckoDetectionProvider', () => {
  it('worker에 raw bytes와 allowlisted metadata만 보낸다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(Response.json(workerResult));
    const provider = new HttpGeckoDetectionProvider({
      baseUrl: 'https://yolo-preview.example.test',
      token: 's'.repeat(43),
      fetchImpl,
    });

    await expect(provider.analyze(input)).resolves.toEqual(workerResult);
    expect(fetchImpl).toHaveBeenCalledOnce();
    const [url, init] = fetchImpl.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('https://yolo-preview.example.test/v1/infer');
    expect(init).toMatchObject({ method: 'POST', cache: 'no-store' });
    expect(new Uint8Array(init.body as ArrayBuffer)).toEqual(input.bytes);
    expect(init.headers).toEqual({
      Authorization: `Bearer ${'s'.repeat(43)}`,
      'Cache-Control': 'no-store',
      'Content-Type': 'image/jpeg',
      'X-Media-Kind': 'image',
      'X-Request-Id': input.requestId,
      'X-Training-Consent': 'false',
    });
    expect(init.signal).toBeInstanceOf(AbortSignal);
  });

  it('HTTPS가 아닌 worker URL과 짧은 token을 거부한다', () => {
    expect(() => new HttpGeckoDetectionProvider({
      baseUrl: 'http://worker.example.test', token: 's'.repeat(43), fetchImpl: fetch,
    })).toThrow('worker_config_invalid');
    expect(() => new HttpGeckoDetectionProvider({
      baseUrl: 'https://worker.example.test', token: 'short', fetchImpl: fetch,
    })).toThrow('worker_config_invalid');
  });

  it('worker 오류와 invalid JSON에서 URL이나 token을 노출하지 않는다', async () => {
    const fetchImpl = vi.fn()
      .mockResolvedValueOnce(new Response('checkpoint /private/secret', { status: 500 }))
      .mockResolvedValueOnce(new Response('not-json', { status: 200 }));
    const provider = new HttpGeckoDetectionProvider({
      baseUrl: 'https://yolo-preview.example.test',
      token: 's'.repeat(43),
      fetchImpl,
    });

    await expect(provider.analyze(input)).rejects.toThrow('inference_unavailable');
    await expect(provider.analyze(input)).rejects.toThrow('inference_unavailable');
  });

  it('worker의 안전한 422 입력 거부는 일반 추론 장애와 구분한다', async () => {
    const provider = new HttpGeckoDetectionProvider({
      baseUrl: 'https://yolo-preview.example.test',
      token: 's'.repeat(43),
      fetchImpl: vi.fn().mockResolvedValue(
        Response.json({ detail: 'media_invalid' }, { status: 422 }),
      ),
    });

    await expect(provider.analyze(input)).rejects.toBeInstanceOf(DetectionInputRejectedError);
  });
});
