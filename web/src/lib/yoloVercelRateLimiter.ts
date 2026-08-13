import 'server-only';

import { checkRateLimit } from '@vercel/firewall';

import type { RateLimiter, RateLimitResult } from './yoloDetectionServer';

export const YOLO_RATE_LIMIT_ID = 'yolo-labeling-assist-ip';

export type RateLimitCheck = typeof checkRateLimit;

export class VercelWafRateLimiter implements RateLimiter {
  readonly scope = 'distributed' as const;

  constructor(private readonly check: RateLimitCheck = checkRateLimit) {}

  async consume(
    _key: string,
    _nowMs: number,
    request: Request,
  ): Promise<RateLimitResult> {
    try {
      const result = await this.check(YOLO_RATE_LIMIT_ID, { request });
      if (result.error) {
        return { allowed: false, retryAfterSec: 0, unavailable: true };
      }
      return result.rateLimited
        ? { allowed: false, retryAfterSec: 600 }
        : { allowed: true, retryAfterSec: 0 };
    } catch {
      return { allowed: false, retryAfterSec: 0, unavailable: true };
    }
  }
}
