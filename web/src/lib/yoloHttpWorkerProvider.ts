import 'server-only';

import { validateDetectionResult, type GeckoDetectionResult } from './yoloDetection';
import type { DetectionInput, GeckoDetectionProvider } from './yoloDetectionServer';

const MAX_RESPONSE_BYTES = 2 * 1024 * 1024;
const MODEL_VERSION = 'v2.6-warm-start-s28';

async function readBoundedJson(response: Response): Promise<unknown> {
  if (!response.ok || !response.body) throw new Error('inference unavailable');
  const declared = Number(response.headers.get('content-length'));
  if (Number.isFinite(declared) && declared > MAX_RESPONSE_BYTES) {
    throw new Error('inference unavailable');
  }
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > MAX_RESPONSE_BYTES) {
        await reader.cancel();
        throw new Error('inference unavailable');
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  const joined = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    joined.set(chunk, offset);
    offset += chunk.byteLength;
  }
  try {
    return JSON.parse(new TextDecoder().decode(joined));
  } catch {
    throw new Error('inference unavailable');
  }
}

function uploadName(contentType: string): string {
  const suffix = new Map([
    ['image/jpeg', '.jpg'], ['image/png', '.png'], ['image/webp', '.webp'],
    ['video/mp4', '.mp4'], ['video/webm', '.webm'],
  ]).get(contentType);
  if (!suffix) throw new Error('inference unavailable');
  return `media${suffix}`;
}

export class HttpGeckoDetectionProvider implements GeckoDetectionProvider {
  readonly mode = 'worker' as const;
  private readonly url: string;
  private readonly token: string;
  private readonly fetcher: typeof fetch;
  private readonly timeoutMs: number;

  constructor(config: { url: string; token: string; fetcher?: typeof fetch; timeoutMs: number }) {
    const url = new URL(config.url);
    if (
      url.protocol !== 'https:'
      || url.username !== ''
      || url.password !== ''
      || url.hash !== ''
      || url.search !== ''
      || url.pathname !== '/v1/infer'
    ) {
      throw new Error('YOLO worker URL must be exact HTTPS /v1/infer');
    }
    if (!config.token || config.token.length > 512) throw new Error('invalid YOLO worker token');
    if (!Number.isInteger(config.timeoutMs) || config.timeoutMs < 1 || config.timeoutMs >= 300_000) {
      throw new Error('invalid YOLO worker timeout');
    }
    this.url = url.toString();
    this.token = config.token;
    this.fetcher = config.fetcher ?? fetch;
    this.timeoutMs = config.timeoutMs;
  }

  async analyze(input: DetectionInput): Promise<GeckoDetectionResult> {
    try {
      const bytes = new Uint8Array(input.bytes.byteLength);
      bytes.set(input.bytes);
      const form = new FormData();
      form.set('media', new Blob([bytes], { type: input.contentType }), uploadName(input.contentType));
      form.set('request_id', input.requestId);
      form.set('training_consent', String(input.trainingConsent));
      const response = await this.fetcher(this.url, {
        method: 'POST',
        redirect: 'error',
        cache: 'no-store',
        headers: { Authorization: `Bearer ${this.token}` },
        body: form,
        signal: AbortSignal.timeout(this.timeoutMs),
      });
      const result = validateDetectionResult(await readBoundedJson(response));
      const expectedContribution = input.trainingConsent ? 'candidate_only' : 'not_requested';
      if (
        !result
        || result.request_id !== input.requestId
        || result.media_kind !== input.mediaKind
        || result.model_version !== MODEL_VERSION
        || result.provider_mode !== 'worker'
        || result.contribution_status !== expectedContribution
      ) {
        throw new Error('inference unavailable');
      }
      return result;
    } catch {
      throw new Error('inference unavailable');
    }
  }
}
