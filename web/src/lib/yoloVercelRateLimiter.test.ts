import { describe, expect, it, vi } from 'vitest';

import { VercelWafRateLimiter, YOLO_RATE_LIMIT_ID } from './yoloVercelRateLimiter';

const request = new Request('https://label.tera-ai.uk/api/yolo-demo/infer', { method: 'POST' });

describe('VercelWafRateLimiter', () => {
  it('Vercel WAF가 허용한 요청만 공통 limiter에서 허용한다', async () => {
    const check = vi.fn().mockResolvedValue({ rateLimited: false });
    const limiter = new VercelWafRateLimiter(check);

    await expect(limiter.consume('ignored', 0, request)).resolves.toEqual({
      allowed: true,
      retryAfterSec: 0,
    });
    expect(check).toHaveBeenCalledWith(YOLO_RATE_LIMIT_ID, { request });
  });

  it('Vercel WAF가 제한한 요청은 fixed-window retry와 함께 거부한다', async () => {
    const limiter = new VercelWafRateLimiter(
      vi.fn().mockResolvedValue({ rateLimited: true }),
    );

    await expect(limiter.consume('ignored', 0, request)).resolves.toEqual({
      allowed: false,
      retryAfterSec: 600,
    });
  });

  it('Vercel WAF 확인 실패는 제한 초과가 아니라 unavailable로 닫는다', async () => {
    const limiter = new VercelWafRateLimiter(
      vi.fn().mockRejectedValue(new Error('waf unavailable')),
    );

    await expect(limiter.consume('ignored', 0, request)).resolves.toEqual({
      allowed: false,
      retryAfterSec: 0,
      unavailable: true,
    });
  });

  it('Vercel WAF rule 미구성 응답도 unavailable로 닫는다', async () => {
    const limiter = new VercelWafRateLimiter(
      vi.fn().mockResolvedValue({ rateLimited: false, error: 'not-found' }),
    );

    await expect(limiter.consume('ignored', 0, request)).resolves.toEqual({
      allowed: false,
      retryAfterSec: 0,
      unavailable: true,
    });
  });
});
