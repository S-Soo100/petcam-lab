import { randomUUID } from 'node:crypto';

import {
  FakeGeckoDetectionProvider,
  InMemoryRateLimiter,
  createInferHandler,
  type InferDependencies,
} from '@/lib/yoloDetectionServer';
import { createProductionDependencies } from '@/lib/yoloProductionDependencies';

export const runtime = 'nodejs';
export const maxDuration = 300;

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
