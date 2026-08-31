import { randomUUID } from 'node:crypto';

import {
  FakeGeckoDetectionProvider,
  InMemoryRateLimiter,
  createInferHandler,
  type InferDependencies,
} from '@/lib/yoloDetectionServer';
import { HttpGeckoDetectionProvider } from '@/lib/yoloHttpWorkerProvider';
import { SupabaseYoloRateLimiter } from '@/lib/yoloRateLimitServer';

export const runtime = 'nodejs';
export const maxDuration = 300;

const V26_IDENTITY = '89e4738a60ebb71900e05e96f5b7262e8b900f5c9bba9b9cb9e34fca36f789b7';

type ProductionEnv = Record<string, string | undefined>;

export function createProductionDependencies(env: ProductionEnv): InferDependencies | null {
  if (
    !env.YOLO_WORKER_URL
    || !env.YOLO_WORKER_TOKEN
    || !env.YOLO_RATE_LIMIT_HMAC_SECRET
    || env.GME_ACTIVE_DETECTOR_IDENTITY !== V26_IDENTITY
  ) return null;
  try {
    return {
      provider: new HttpGeckoDetectionProvider({
        url: env.YOLO_WORKER_URL,
        token: env.YOLO_WORKER_TOKEN,
        timeoutMs: 180_000,
      }),
      limiter: new SupabaseYoloRateLimiter({ hmacSecret: env.YOLO_RATE_LIMIT_HMAC_SECRET }),
      now: () => new Date(),
      requestId: randomUUID,
      environment: 'production',
    };
  } catch {
    return null;
  }
}

const dependencies: InferDependencies | null = process.env.NODE_ENV === 'production'
  ? createProductionDependencies(process.env)
  : {
      provider: new FakeGeckoDetectionProvider(),
      limiter: new InMemoryRateLimiter({ limit: 5, windowMs: 600_000 }),
      now: () => new Date(),
      requestId: randomUUID,
      environment: process.env.NODE_ENV,
    };

export const POST = dependencies
  ? createInferHandler(dependencies)
  : async () => Response.json(
      { detail: '연구 추론기가 준비되지 않았어.' },
      { status: 503, headers: { 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' } },
    );
