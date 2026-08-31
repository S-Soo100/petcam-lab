import { randomUUID } from 'node:crypto';

import type { InferDependencies } from '@/lib/yoloDetectionServer';
import { HttpGeckoDetectionProvider } from '@/lib/yoloHttpWorkerProvider';
import { SupabaseYoloRateLimiter } from '@/lib/yoloRateLimitServer';

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
