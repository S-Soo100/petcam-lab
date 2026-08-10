import 'server-only';

import { randomUUID } from 'node:crypto';

import {
  FakeGeckoDetectionProvider,
  InMemoryRateLimiter,
  createInferHandler,
  type GeckoDetectionProvider,
} from './yoloDetectionServer';
import { HttpGeckoDetectionProvider } from './yoloHttpProvider';

type DeploymentTarget = 'development' | 'test' | 'preview' | 'production';
type FetchLike = (input: string | URL | Request, init?: RequestInit) => Promise<Response>;
type RouteEnvironment = Record<string, string | undefined>;

export function deploymentTarget(env: RouteEnvironment): DeploymentTarget {
  if (env.VERCEL_ENV === 'preview') return 'preview';
  if (env.VERCEL_ENV === 'production') return 'production';
  if (env.NODE_ENV === 'test') return 'test';
  if (env.NODE_ENV === 'production') return 'production';
  return 'development';
}

export function createPostFromEnv(
  env: RouteEnvironment,
  fetchImpl: FetchLike = fetch,
) {
  const environment = deploymentTarget(env);
  let provider: GeckoDetectionProvider = new FakeGeckoDetectionProvider();
  if (
    environment === 'preview'
    && env.YOLO_PREVIEW_ENABLED === 'true'
    && env.YOLO_WORKER_URL
    && env.YOLO_WORKER_TOKEN
  ) {
    try {
      provider = new HttpGeckoDetectionProvider({
        baseUrl: env.YOLO_WORKER_URL,
        token: env.YOLO_WORKER_TOKEN,
        fetchImpl,
      });
    } catch {
      provider = new FakeGeckoDetectionProvider();
    }
  }
  return createInferHandler({
    provider,
    limiter: new InMemoryRateLimiter({ limit: 5, windowMs: 600_000 }),
    now: () => new Date(),
    requestId: randomUUID,
    environment,
  });
}
