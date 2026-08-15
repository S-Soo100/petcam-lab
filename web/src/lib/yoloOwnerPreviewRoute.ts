import 'server-only';

import { randomUUID } from 'node:crypto';

import type { NextRequest } from 'next/server';

import type { OwnerResult } from './labelingAccess';
import {
  InMemoryRateLimiter,
  createInferHandler,
} from './yoloDetectionServer';
import { HttpGeckoDetectionProvider, parseHttpWorkerConfig } from './yoloHttpProvider';

type FetchLike = (input: string | URL | Request, init?: RequestInit) => Promise<Response>;
type RouteEnvironment = Record<string, string | undefined>;
type RequireOwner = (request: NextRequest) => Promise<OwnerResult>;

const V25_WORKER_ORIGIN = 'https://yolo-v25-preview.tera-ai.uk';
const V25_MODEL_VERSION = 'yolo26n-owner-dataset-v2.5-warm-start+2b128f105e89';

function json(body: unknown, status: number): Response {
  return Response.json(body, {
    status,
    headers: {
      'Cache-Control': 'no-store',
      'X-Content-Type-Options': 'nosniff',
    },
  });
}

export function ownerPreviewWorkerConfig(
  env: RouteEnvironment,
): { baseUrl: string; token: string } | null {
  if (env.VERCEL_ENV !== 'preview') return null;
  if (env.YOLO_V25_OWNER_PREVIEW_ENABLED !== 'true') return null;
  const config = parseHttpWorkerConfig(
    env.YOLO_V25_OWNER_WORKER_URL,
    env.YOLO_V25_OWNER_WORKER_TOKEN,
  );
  if (!config || config.baseUrl !== V25_WORKER_ORIGIN) return null;
  return config;
}

export function createOwnerPreviewPost(options: {
  env: RouteEnvironment;
  requireOwner: RequireOwner;
  fetchImpl?: FetchLike;
}) {
  const limiter = new InMemoryRateLimiter({ limit: 5, windowMs: 600_000 });

  return async function POST(request: NextRequest): Promise<Response> {
    const access = await options.requireOwner(request);
    if (!access.ok) return access.response;

    // 이 endpoint 자체를 Vercel Preview 밖에서는 숨겨 production 승격을 fail-closed 한다.
    if (options.env.VERCEL_ENV !== 'preview') {
      return json({ detail: 'not found' }, 404);
    }
    const config = ownerPreviewWorkerConfig(options.env);
    if (!config) {
      return json({ detail: 'YOLO v2.5 Owner Preview가 준비되지 않았어.' }, 503);
    }

    let provider: HttpGeckoDetectionProvider;
    try {
      provider = new HttpGeckoDetectionProvider({
        baseUrl: config.baseUrl,
        token: config.token,
        fetchImpl: options.fetchImpl,
      });
    } catch {
      return json({ detail: 'YOLO v2.5 Owner Preview가 준비되지 않았어.' }, 503);
    }

    return createInferHandler({
      provider,
      limiter,
      now: () => new Date(),
      requestId: randomUUID,
      environment: 'preview',
      trainingConsentPolicy: 'forbidden',
      expectedWorkerIdentity: {
        modelVersion: V25_MODEL_VERSION,
        threshold: 0.20,
        developmentOnly: true,
        usageScope: 'owner_preview_bbox_suggestion_only',
      },
    })(request);
  };
}
