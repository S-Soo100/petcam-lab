import 'server-only';

import { randomUUID } from 'node:crypto';

import {
  FakeGeckoDetectionProvider,
  InMemoryRateLimiter,
  createInferHandler,
  type GeckoDetectionProvider,
} from './yoloDetectionServer';
import { HttpGeckoDetectionProvider, parseHttpWorkerConfig } from './yoloHttpProvider';
import { VercelWafRateLimiter, type RateLimitCheck } from './yoloVercelRateLimiter';

type DeploymentTarget = 'development' | 'test' | 'preview' | 'production';
type FetchLike = (input: string | URL | Request, init?: RequestInit) => Promise<Response>;
type RouteEnvironment = Record<string, string | undefined>;

const PRODUCTION_WORKER_ORIGIN = 'https://yolo-v23-preview.tera-ai.uk';
const PRODUCTION_MODEL_VERSION = 'yolo26n-owner-dataset-v2.3-warm-start+dbed3a2d8018';

export function deploymentTarget(env: RouteEnvironment): DeploymentTarget {
  if (env.VERCEL_ENV === 'preview') return 'preview';
  if (env.VERCEL_ENV === 'production') return 'production';
  if (env.NODE_ENV === 'test') return 'test';
  if (env.NODE_ENV === 'production') return 'production';
  return 'development';
}

export function labelingAssistConfig(
  env: RouteEnvironment,
): { baseUrl: string; token: string } | null {
  const environment = deploymentTarget(env);
  const enabled = (environment === 'preview' && env.YOLO_PREVIEW_ENABLED === 'true')
    || (environment === 'production' && env.YOLO_LABELING_ASSIST_ENABLED === 'true');
  if (!enabled) return null;
  const config = parseHttpWorkerConfig(env.YOLO_WORKER_URL, env.YOLO_WORKER_TOKEN);
  if (!config) return null;
  if (environment === 'production' && config.baseUrl !== PRODUCTION_WORKER_ORIGIN) return null;
  return config;
}

export function labelingAssistEnabled(env: RouteEnvironment): boolean {
  return labelingAssistConfig(env) !== null;
}

export function createPostFromEnv(
  env: RouteEnvironment,
  fetchImpl: FetchLike = fetch,
  rateLimitCheck?: RateLimitCheck,
) {
  const environment = deploymentTarget(env);
  const assistConfig = labelingAssistConfig(env);
  let provider: GeckoDetectionProvider = new FakeGeckoDetectionProvider();
  if (assistConfig) {
    try {
      provider = new HttpGeckoDetectionProvider({
        baseUrl: assistConfig.baseUrl,
        token: assistConfig.token,
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
    expectedWorkerIdentity: environment === 'production' ? {
      modelVersion: PRODUCTION_MODEL_VERSION,
      threshold: 0.25,
      developmentOnly: true,
      usageScope: 'labeling_bbox_assist_only',
    } : undefined,
  });
}
