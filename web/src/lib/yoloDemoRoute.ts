import 'server-only';

import { randomUUID } from 'node:crypto';

import {
  FakeGeckoDetectionProvider,
  InMemoryRateLimiter,
  createInferHandler,
  type GeckoDetectionProvider,
} from './yoloDetectionServer';
import { HttpGeckoDetectionProvider } from './yoloHttpProvider';
import { VercelWafRateLimiter, type RateLimitCheck } from './yoloVercelRateLimiter';

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

export function labelingAssistEnabled(env: RouteEnvironment): boolean {
  const environment = deploymentTarget(env);
  const enabled = (environment === 'preview' && env.YOLO_PREVIEW_ENABLED === 'true')
    || (environment === 'production' && env.YOLO_LABELING_ASSIST_ENABLED === 'true');
  return enabled && Boolean(env.YOLO_WORKER_URL && env.YOLO_WORKER_TOKEN);
}

export function createPostFromEnv(
  env: RouteEnvironment,
  fetchImpl: FetchLike = fetch,
  rateLimitCheck?: RateLimitCheck,
) {
  const environment = deploymentTarget(env);
  let provider: GeckoDetectionProvider = new FakeGeckoDetectionProvider();
  if (
    labelingAssistEnabled(env)
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
    limiter: environment === 'production'
      ? new VercelWafRateLimiter(rateLimitCheck)
      : new InMemoryRateLimiter({ limit: 5, windowMs: 600_000 }),
    now: () => new Date(),
    requestId: randomUUID,
    environment,
  });
}
