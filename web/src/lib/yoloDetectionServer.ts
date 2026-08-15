import 'server-only';

import {
  validateDetectionResult,
  type GeckoDetectionResult,
  type MediaKind,
} from './yoloDetection';

const IMAGE_LIMIT = 10 * 1024 * 1024;
const VIDEO_LIMIT = 50 * 1024 * 1024;
const MULTIPART_LIMIT = VIDEO_LIMIT + 1024 * 1024;
const WARNING = '연구용 결과이며 오류 가능';

export interface DetectionLimits {
  decodeTimeoutMs: number;
  imageMaxPixels: number;
  maxVideoDurationMs: number;
  maxVideoFps: number;
  maxVideoWidth: number;
  maxVideoHeight: number;
  temporaryStorageTtlSec: number;
}

export const DETECTION_LIMITS: DetectionLimits = {
  decodeTimeoutMs: 15_000,
  imageMaxPixels: 20_000_000,
  maxVideoDurationMs: 60_000,
  maxVideoFps: 30,
  maxVideoWidth: 1920,
  maxVideoHeight: 1080,
  temporaryStorageTtlSec: 900,
};

export interface DetectionInput {
  requestId: string;
  bytes: Uint8Array;
  mediaKind: MediaKind;
  contentType: string;
  originalSize: number;
  trainingConsent: boolean;
  limits: DetectionLimits;
}

export interface GeckoDetectionProvider {
  readonly mode: 'fake' | 'worker';
  analyze(input: DetectionInput): Promise<GeckoDetectionResult>;
}

export class DetectionInputRejectedError extends Error {
  constructor() {
    super('worker_input_invalid');
    this.name = 'DetectionInputRejectedError';
  }
}

export interface MediaSignature {
  kind: MediaKind;
  contentType: string;
}

function declaredMedia(type: string): MediaSignature | null {
  if (type === 'image/jpeg' || type === 'image/png' || type === 'image/webp') {
    return { kind: 'image', contentType: type };
  }
  if (type === 'video/mp4' || type === 'video/webm') {
    return { kind: 'video', contentType: type };
  }
  return null;
}

function startsWith(bytes: Uint8Array, signature: readonly number[]): boolean {
  return signature.every((value, index) => bytes[index] === value);
}

function ascii(bytes: Uint8Array, offset: number, value: string): boolean {
  for (let index = 0; index < value.length; index += 1) {
    if (bytes[offset + index] !== value.charCodeAt(index)) return false;
  }
  return true;
}

export function sniffMedia(bytes: Uint8Array, declaredType: string): MediaSignature | null {
  const detected = (() => {
    if (startsWith(bytes, [0xff, 0xd8, 0xff])) return { kind: 'image', contentType: 'image/jpeg' } as const;
    if (startsWith(bytes, [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])) {
      return { kind: 'image', contentType: 'image/png' } as const;
    }
    if (ascii(bytes, 0, 'RIFF') && ascii(bytes, 8, 'WEBP')) {
      return { kind: 'image', contentType: 'image/webp' } as const;
    }
    if (bytes.length >= 12 && ascii(bytes, 4, 'ftyp')) {
      return { kind: 'video', contentType: 'video/mp4' } as const;
    }
    if (startsWith(bytes, [0x1a, 0x45, 0xdf, 0xa3])) {
      return { kind: 'video', contentType: 'video/webm' } as const;
    }
    return null;
  })();
  return detected?.contentType === declaredType ? detected : null;
}

export function mediaSizeAllowed(kind: MediaKind, size: number): boolean {
  if (!Number.isInteger(size) || size <= 0) return false;
  return size <= (kind === 'image' ? IMAGE_LIMIT : VIDEO_LIMIT);
}

export class FakeGeckoDetectionProvider implements GeckoDetectionProvider {
  readonly mode = 'fake' as const;

  async analyze(input: DetectionInput): Promise<GeckoDetectionResult> {
    const detected = {
      label: 'gecko' as const,
      confidence: 0.87,
      bbox: { x: 0.18, y: 0.2, width: 0.42, height: 0.35 },
    };
    const timestamps = input.mediaKind === 'image' ? [0] : [0, 1000, 2000];
    return {
      request_id: input.requestId,
      media_kind: input.mediaKind,
      model_version: 'fake-yolo-v0',
      provider_mode: 'fake',
      processed_at: new Date().toISOString(),
      warning: WARNING,
      frames: timestamps.map((timestamp, index) => ({
        frame_index: index,
        timestamp_ms: timestamp,
        detections: index === 1 ? [] : [detected],
      })),
      contribution_status: input.trainingConsent ? 'candidate_only' : 'not_requested',
    };
  }
}

export interface RateLimitResult {
  allowed: boolean;
  retryAfterSec: number;
  unavailable?: boolean;
}

export interface RateLimiter {
  readonly scope?: 'local' | 'distributed';
  consume(
    key: string,
    nowMs: number,
    request: Request,
  ): RateLimitResult | Promise<RateLimitResult>;
}

export class InMemoryRateLimiter implements RateLimiter {
  readonly scope = 'local' as const;
  private readonly attempts = new Map<string, number[]>();

  constructor(private readonly config: { limit: number; windowMs: number; maxKeys?: number }) {}

  consume(key: string, nowMs: number): RateLimitResult {
    const cutoff = nowMs - this.config.windowMs;
    this.attempts.forEach((timestamps, storedKey) => {
      if (timestamps[timestamps.length - 1] <= cutoff) this.attempts.delete(storedKey);
    });
    const maxKeys = this.config.maxKeys ?? 10_000;
    if (!this.attempts.has(key) && this.attempts.size >= maxKeys) {
      return { allowed: false, retryAfterSec: Math.ceil(this.config.windowMs / 1000) };
    }
    const current = (this.attempts.get(key) ?? []).filter((timestamp) => timestamp > cutoff);
    if (current.length >= this.config.limit) {
      const remainingMs = Math.max(1, current[0] + this.config.windowMs - nowMs);
      return { allowed: false, retryAfterSec: Math.ceil(remainingMs / 1000) };
    }
    current.push(nowMs);
    this.attempts.set(key, current);
    return { allowed: true, retryAfterSec: 0 };
  }
}

export interface InferDependencies {
  provider: GeckoDetectionProvider;
  limiter: RateLimiter;
  now: () => Date;
  requestId: () => string;
  environment: 'development' | 'test' | 'preview' | 'production';
  expectedWorkerIdentity?: {
    modelVersion: string;
    threshold: number;
    developmentOnly: true;
    usageScope: 'labeling_bbox_assist_only' | 'owner_preview_bbox_suggestion_only';
  };
  trainingConsentPolicy?: 'optional' | 'forbidden';
}

function json(body: unknown, status: number, extraHeaders: Record<string, string> = {}): Response {
  return Response.json(body, {
    status,
    headers: {
      'Cache-Control': 'no-store',
      'X-Content-Type-Options': 'nosniff',
      ...extraHeaders,
    },
  });
}

function requesterKey(request: Request, environment: InferDependencies['environment']): string {
  const trustedForwarded = request.headers.get('x-vercel-forwarded-for')?.split(',')[0]?.trim();
  const developmentForwarded = environment === 'production'
    ? null
    : request.headers.get('x-forwarded-for')?.split(',')[0]?.trim();
  return (trustedForwarded || request.headers.get('x-real-ip') || developmentForwarded || 'unknown').slice(0, 128);
}

export function createInferHandler(deps: InferDependencies) {
  return async function POST(request: Request): Promise<Response> {
    if (deps.environment === 'preview' && deps.provider.mode !== 'worker') {
      return json({ detail: '보호된 YOLO Preview가 준비되지 않았어.' }, 503);
    }
    if (deps.environment === 'production' && deps.limiter.scope !== 'distributed') {
      return json({ detail: '연구 추론기가 준비되지 않았어.' }, 503);
    }
    if (deps.environment === 'production' && deps.provider.mode === 'fake') {
      return json({ detail: '연구 추론기가 준비되지 않았어.' }, 503);
    }
    const declaredLength = Number(request.headers.get('content-length'));
    if (Number.isFinite(declaredLength) && declaredLength > MULTIPART_LIMIT) {
      return json({ detail: '업로드 전체 크기가 허용 한도를 넘었어.' }, 413);
    }
    const limited = await deps.limiter.consume(
      requesterKey(request, deps.environment),
      deps.now().getTime(),
      request,
    );
    if (limited.unavailable) {
      return json({ detail: '연구 추론기가 준비되지 않았어.' }, 503);
    }
    if (!limited.allowed) {
      return json(
        { detail: '요청 횟수가 너무 많아. 잠시 뒤 다시 시도해.' },
        429,
        { 'Retry-After': String(limited.retryAfterSec) },
      );
    }

    let form: FormData;
    try {
      form = await request.formData();
    } catch {
      return json({ detail: '업로드 형식이 올바르지 않아.' }, 400);
    }
    const keys: string[] = [];
    form.forEach((_value, key) => keys.push(key));
    if (keys.some((key) => key !== 'media' && key !== 'training_consent')) {
      return json({ detail: '허용되지 않은 입력 항목이 있어.' }, 400);
    }
    if (form.getAll('media').length !== 1 || form.getAll('training_consent').length !== 1) {
      return json({ detail: '파일과 학습 제공 선택값은 하나씩만 보내야 해.' }, 400);
    }
    const consent = form.get('training_consent');
    if (consent !== 'true' && consent !== 'false') {
      return json({ detail: '학습 제공 선택값이 올바르지 않아.' }, 400);
    }
    if (deps.trainingConsentPolicy === 'forbidden' && consent !== 'false') {
      return json({ detail: 'Owner Preview 결과는 학습 제공으로 전환할 수 없어.' }, 400);
    }
    const media = form.get('media');
    if (!(media instanceof File)) return json({ detail: '파일 하나를 선택해.' }, 400);

    const declared = declaredMedia(media.type);
    if (!declared) return json({ detail: '지원하지 않는 파일 형식이야.' }, 415);
    // multipart body를 다시 큰 Uint8Array로 복제하기 전에 선언 형식 기준 상한부터 확인한다.
    if (!mediaSizeAllowed(declared.kind, media.size)) {
      return json(
        { detail: declared.kind === 'image' ? '사진은 10 MiB 이하여야 해.' : '영상은 50 MiB 이하여야 해.' },
        413,
      );
    }
    const bytes = new Uint8Array(await media.arrayBuffer());
    const signature = sniffMedia(bytes, media.type);
    if (!signature) return json({ detail: '지원하지 않거나 실제 형식과 다른 파일이야.' }, 415);
    try {
      const requestId = deps.requestId();
      const result = await deps.provider.analyze({
        requestId,
        bytes,
        mediaKind: signature.kind,
        contentType: signature.contentType,
        originalSize: media.size,
        trainingConsent: consent === 'true',
        limits: DETECTION_LIMITS,
      });
      const safe = validateDetectionResult(result);
      if (!safe) return json({ detail: 'inference unavailable' }, 502);
      const expectedContribution = consent === 'true' ? 'candidate_only' : 'not_requested';
      if (
        safe.request_id !== requestId
        || safe.media_kind !== signature.kind
        || safe.provider_mode !== deps.provider.mode
        || safe.contribution_status !== expectedContribution
      ) {
        return json({ detail: 'inference unavailable' }, 502);
      }
      if (
        deps.expectedWorkerIdentity
        && (
          safe.model_version !== deps.expectedWorkerIdentity.modelVersion
          || safe.threshold !== deps.expectedWorkerIdentity.threshold
          || safe.development_only !== deps.expectedWorkerIdentity.developmentOnly
          || safe.usage_scope !== deps.expectedWorkerIdentity.usageScope
        )
      ) {
        return json({ detail: 'inference unavailable' }, 502);
      }
      return json(safe, 200);
    } catch (error) {
      if (error instanceof DetectionInputRejectedError) {
        return json(
          {
            detail: signature.kind === 'image'
              ? '사진을 읽지 못했어. 20MP 이하의 정상 JPEG, PNG, WebP 파일인지 확인해.'
              : '영상을 읽지 못했어. 60초 이하의 정상 MP4, WebM 파일인지 확인해.',
          },
          422,
        );
      }
      return json({ detail: 'inference unavailable' }, 502);
    }
  };
}
