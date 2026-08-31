import { describe, expect, it, vi } from 'vitest';

import type { GeckoDetectionResult } from './yoloDetection';
import { DETECTION_LIMITS, type DetectionInput } from './yoloDetectionServer';
import { HttpGeckoDetectionProvider } from './yoloHttpWorkerProvider';

const INPUT: DetectionInput = {
  requestId: 'req-v26',
  bytes: new Uint8Array([0xff, 0xd8, 0xff, 0xe0]),
  mediaKind: 'image',
  contentType: 'image/jpeg',
  originalSize: 4,
  trainingConsent: false,
  limits: DETECTION_LIMITS,
};

const RESULT: GeckoDetectionResult = {
  request_id: 'req-v26',
  media_kind: 'image',
  model_version: 'v2.6-warm-start-s28',
  provider_mode: 'worker',
  processed_at: '2026-08-31T15:00:00.000Z',
  warning: '연구용 결과이며 오류 가능',
  frames: [{ frame_index: 0, timestamp_ms: 0, detections: [] }],
  contribution_status: 'not_requested',
};

function provider(fetcher: typeof fetch) {
  return new HttpGeckoDetectionProvider({
    url: 'https://yolo-worker.tera-ai.uk/v1/infer',
    token: 'worker-token',
    fetcher,
    timeoutMs: 180_000,
  });
}

describe('HttpGeckoDetectionProvider', () => {
  it('worker 요청을 인증하고 exact v2.6 응답만 반환한다', async () => {
    const fetcher = vi.fn().mockResolvedValue(Response.json(RESULT)) as unknown as typeof fetch;

    await expect(provider(fetcher).analyze(INPUT)).resolves.toEqual(RESULT);
    expect(fetcher).toHaveBeenCalledWith(
      'https://yolo-worker.tera-ai.uk/v1/infer',
      expect.objectContaining({
        method: 'POST', redirect: 'error', cache: 'no-store',
        headers: { Authorization: 'Bearer worker-token' },
      }),
    );
    const init = (fetcher as unknown as ReturnType<typeof vi.fn>).mock.calls[0][1];
    expect(init.body).toBeInstanceOf(FormData);
    expect(init.body.get('request_id')).toBe('req-v26');
    expect(init.body.get('training_consent')).toBe('false');
  });

  it.each([
    ['wrong request id', { ...RESULT, request_id: 'wrong' }],
    ['wrong model', { ...RESULT, model_version: 'v2.5' }],
    ['wrong provider mode', { ...RESULT, provider_mode: 'fake' }],
    ['wrong consent result', { ...RESULT, contribution_status: 'candidate_only' }],
  ])('%s 응답은 원문을 노출하지 않고 unavailable로 거부한다', async (_label, result) => {
    const fetcher = vi.fn().mockResolvedValue(Response.json(result)) as unknown as typeof fetch;
    await expect(provider(fetcher).analyze(INPUT)).rejects.toThrow('inference unavailable');
  });

  it('HTTPS가 아니거나 redirect·2MiB 초과 응답이면 unavailable로 닫는다', async () => {
    expect(() => new HttpGeckoDetectionProvider({
      url: 'http://worker.invalid/v1/infer', token: 'worker-token', fetcher: fetch, timeoutMs: 1,
    })).toThrow(/https/i);

    const redirect = vi.fn().mockResolvedValue(new Response('', { status: 302 })) as unknown as typeof fetch;
    await expect(provider(redirect).analyze(INPUT)).rejects.toThrow('inference unavailable');

    const oversized = vi.fn().mockResolvedValue(new Response('x', {
      headers: { 'content-length': String(2 * 1024 * 1024 + 1) },
    })) as unknown as typeof fetch;
    await expect(provider(oversized).analyze(INPUT)).rejects.toThrow('inference unavailable');
  });
});
