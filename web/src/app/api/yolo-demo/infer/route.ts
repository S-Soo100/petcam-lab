import { randomUUID } from 'node:crypto';

import {
  FakeGeckoDetectionProvider,
  InMemoryRateLimiter,
  createInferHandler,
} from '@/lib/yoloDetectionServer';

export const runtime = 'nodejs';

const provider = new FakeGeckoDetectionProvider();
const limiter = new InMemoryRateLimiter({ limit: 5, windowMs: 600_000 });

export const POST = createInferHandler({
  provider,
  limiter,
  now: () => new Date(),
  requestId: randomUUID,
  environment: process.env.NODE_ENV,
});
