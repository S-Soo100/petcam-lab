import 'server-only';

import {
  DetectionInputRejectedError,
  type DetectionInput,
  type GeckoDetectionProvider,
} from './yoloDetectionServer';
import type { GeckoDetectionResult } from './yoloDetection';

type FetchLike = (input: string | URL | Request, init?: RequestInit) => Promise<Response>;

interface HttpProviderOptions {
  baseUrl: string;
  token: string;
  fetchImpl?: FetchLike;
}

export class HttpGeckoDetectionProvider implements GeckoDetectionProvider {
  readonly mode = 'worker' as const;
  private readonly inferUrl: string;
  private readonly token: string;
  private readonly fetchImpl: FetchLike;

  constructor(options: HttpProviderOptions) {
    let url: URL;
    try {
      url = new URL(options.baseUrl);
    } catch {
      throw new Error('worker_config_invalid');
    }
    if (
      url.protocol !== 'https:'
      || url.username !== ''
      || url.password !== ''
      || (url.pathname !== '' && url.pathname !== '/')
      || url.search !== ''
      || url.hash !== ''
      || new TextEncoder().encode(options.token).byteLength < 32
    ) {
      throw new Error('worker_config_invalid');
    }
    this.inferUrl = new URL('/v1/infer', url).toString();
    this.token = options.token;
    this.fetchImpl = options.fetchImpl ?? fetch;
  }

  async analyze(input: DetectionInput): Promise<GeckoDetectionResult> {
    try {
      const response = await this.fetchImpl(this.inferUrl, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${this.token}`,
          'Cache-Control': 'no-store',
          'Content-Type': input.contentType,
          'X-Media-Kind': input.mediaKind,
          'X-Request-Id': input.requestId,
          'X-Training-Consent': String(input.trainingConsent),
        },
        body: Uint8Array.from(input.bytes).buffer,
        cache: 'no-store',
        signal: AbortSignal.timeout(65_000),
      });
      if (response.status === 422) throw new DetectionInputRejectedError();
      if (!response.ok) throw new Error('worker_response_invalid');
      return await response.json() as GeckoDetectionResult;
    } catch (error) {
      if (error instanceof DetectionInputRejectedError) throw error;
      throw new Error('inference_unavailable');
    }
  }
}
