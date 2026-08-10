import { describe, expect, it } from 'vitest';

import {
  FakeGeckoDetectionProvider,
  InMemoryRateLimiter,
  createInferHandler,
  mediaSizeAllowed,
  sniffMedia,
  type DetectionInput,
  type GeckoDetectionProvider,
} from './yoloDetectionServer';

const jpeg = new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 0, 1]);
const zip = new Uint8Array([0x50, 0x4b, 0x03, 0x04]);

function request(
  bytes: Uint8Array = jpeg,
  contentType = 'image/jpeg',
  consent = 'false',
  ip = '203.0.113.10',
): Request {
  const data = new FormData();
  const content = new Uint8Array(bytes.byteLength);
  content.set(bytes);
  data.set('media', new File([content.buffer], 'client-name.jpg', { type: contentType }));
  data.set('training_consent', consent);
  return new Request('http://localhost/api/yolo-demo/infer', {
    method: 'POST',
    headers: { 'x-forwarded-for': ip },
    body: data,
  });
}

function dependencies(provider: GeckoDetectionProvider = new FakeGeckoDetectionProvider()) {
  return {
    provider,
    limiter: new InMemoryRateLimiter({ limit: 5, windowMs: 600_000 }),
    now: () => new Date('2026-08-10T08:00:00.000Z'),
    requestId: () => 'req-fixed',
    environment: 'test' as const,
  };
}

describe('sniffMedia', () => {
  it('선언 type과 magic byte가 일치할 때만 허용한다', () => {
    expect(sniffMedia(jpeg, 'image/jpeg')).toEqual({
      kind: 'image',
      contentType: 'image/jpeg',
    });
    expect(sniffMedia(zip, 'image/jpeg')).toBeNull();
  });

  it('사진 10 MiB와 영상 50 MiB 경계를 넘기지 않는다', () => {
    expect(mediaSizeAllowed('image', 10 * 1024 * 1024)).toBe(true);
    expect(mediaSizeAllowed('image', 10 * 1024 * 1024 + 1)).toBe(false);
    expect(mediaSizeAllowed('video', 50 * 1024 * 1024)).toBe(true);
    expect(mediaSizeAllowed('video', 50 * 1024 * 1024 + 1)).toBe(false);
  });
});

describe('FakeGeckoDetectionProvider', () => {
  it('같은 입력에 versioned deterministic 결과를 낸다', async () => {
    const input: DetectionInput = {
      requestId: 'req-fixed',
      bytes: jpeg,
      mediaKind: 'image',
      contentType: 'image/jpeg',
      originalSize: jpeg.byteLength,
      trainingConsent: false,
      limits: {
        decodeTimeoutMs: 15_000, imageMaxPixels: 20_000_000, maxVideoDurationMs: 60_000,
        maxVideoFps: 30, maxVideoWidth: 1920, maxVideoHeight: 1080, temporaryStorageTtlSec: 900,
      },
    };
    await expect(new FakeGeckoDetectionProvider().analyze(input)).resolves.toMatchObject({
      request_id: 'req-fixed',
      model_version: 'fake-yolo-v0',
      provider_mode: 'fake',
      media_kind: 'image',
      contribution_status: 'not_requested',
    });
  });
});

describe('createInferHandler', () => {
  it('검증한 공개 upload에 no-store detection 응답을 준다', async () => {
    const response = await createInferHandler(dependencies())(request());
    expect(response.status).toBe(200);
    expect(response.headers.get('cache-control')).toBe('no-store');
    expect(response.headers.get('x-content-type-options')).toBe('nosniff');
    await expect(response.json()).resolves.toMatchObject({
      request_id: 'req-fixed',
      contribution_status: 'not_requested',
    });
  });

  it('알 수 없는 consent와 위장 형식을 거부한다', async () => {
    expect((await createInferHandler(dependencies())(request(jpeg, 'image/jpeg', 'yes'))).status).toBe(400);
    expect((await createInferHandler(dependencies())(request(zip, 'image/jpeg'))).status).toBe(415);
  });

  it('중복 multipart 필드와 용량 초과 파일을 provider 전에 거부한다', async () => {
    const duplicate = new FormData();
    duplicate.append('media', new File([jpeg], 'one.jpg', { type: 'image/jpeg' }));
    duplicate.append('media', new File([jpeg], 'two.jpg', { type: 'image/jpeg' }));
    duplicate.set('training_consent', 'false');

    const duplicateResponse = await createInferHandler(dependencies())(
      new Request('http://localhost/api/yolo-demo/infer', { method: 'POST', body: duplicate }),
    );
    expect(duplicateResponse.status).toBe(400);

    const oversized = new FormData();
    oversized.set(
      'media',
      new File([new Uint8Array(10 * 1024 * 1024 + 1)], 'large.jpg', { type: 'image/jpeg' }),
    );
    oversized.set('training_consent', 'false');
    const oversizedResponse = await createInferHandler(dependencies())(
      new Request('http://localhost/api/yolo-demo/infer', { method: 'POST', body: oversized }),
    );
    expect(oversizedResponse.status).toBe(413);
  });

  it('같은 식별자의 6번째 요청을 429로 막는다', async () => {
    const handler = createInferHandler(dependencies());
    for (let index = 0; index < 5; index += 1) {
      expect((await handler(request())).status).toBe(200);
    }
    const response = await handler(request());
    expect(response.status).toBe(429);
    expect(response.headers.get('retry-after')).toBe('600');
  });

  it('production에서 명시적 허용 없는 fake를 503으로 막는다', async () => {
    const response = await createInferHandler({
      ...dependencies(),
      environment: 'production',
    })(request());
    expect(response.status).toBe(503);
  });

  it('preview에서 worker가 아닌 provider를 503으로 막는다', async () => {
    const response = await createInferHandler({
      ...dependencies(),
      environment: 'preview',
    })(request());
    expect(response.status).toBe(503);
  });

  it('multipart parsing 전에 명백한 전체 body 용량 초과를 413으로 막는다', async () => {
    const response = await createInferHandler(dependencies())(
      new Request('http://localhost/api/yolo-demo/infer', {
        method: 'POST',
        headers: { 'content-length': String(52 * 1024 * 1024) },
        body: 'not-a-multipart-body',
      }),
    );
    expect(response.status).toBe(413);
  });

  it('계약을 어긴 provider 응답을 502로 숨긴다', async () => {
    const provider: GeckoDetectionProvider = {
      mode: 'worker',
      async analyze() {
        return { frames: 'broken' } as never;
      },
    };
    const response = await createInferHandler(dependencies(provider))(request());
    expect(response.status).toBe(502);
    expect(await response.json()).toEqual({ detail: 'inference unavailable' });
  });

  it('provider가 요청 identity나 동의 상태를 바꾸면 502로 닫는다', async () => {
    const fake = new FakeGeckoDetectionProvider();
    const provider: GeckoDetectionProvider = {
      mode: 'worker',
      async analyze(input) {
        return {
          ...(await fake.analyze(input)),
          request_id: 'different-request',
          provider_mode: 'worker',
          contribution_status: 'candidate_only',
        };
      },
    };
    const response = await createInferHandler(dependencies(provider))(request());
    expect(response.status).toBe(502);
  });
});
