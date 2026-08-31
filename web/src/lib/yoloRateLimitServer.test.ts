import { createHmac } from 'node:crypto';

import { describe, expect, it, vi } from 'vitest';

import { SupabaseYoloRateLimiter } from './yoloRateLimitServer';

const NOW = Date.parse('2026-08-31T15:00:00.000Z');

describe('SupabaseYoloRateLimiter', () => {
  it('requester identity를 HMAC한 뒤 RPC를 호출하고 retry 시간을 매핑한다', async () => {
    const rpc = vi.fn().mockResolvedValue({
      data: { allowed: false, retry_after_sec: 42 }, error: null,
    });
    const secret = 's'.repeat(32);
    const limiter = new SupabaseYoloRateLimiter({ hmacSecret: secret, rpc });

    await expect(limiter.consume('203.0.113.7', NOW)).resolves.toEqual({
      allowed: false, retryAfterSec: 42,
    });
    expect(rpc).toHaveBeenCalledWith('fn_consume_yolo_demo_rate_limit', {
      p_key_hash: createHmac('sha256', secret).update('203.0.113.7').digest('hex'),
      p_now: '2026-08-31T15:00:00.000Z',
      p_limit: 5,
      p_window_sec: 600,
    });
    expect(JSON.stringify(rpc.mock.calls)).not.toContain('203.0.113.7');
  });

  it('RPC 오류나 invalid 응답은 허용으로 오인하지 않는다', async () => {
    const failed = new SupabaseYoloRateLimiter({
      hmacSecret: 's'.repeat(32),
      rpc: vi.fn().mockResolvedValue({ data: null, error: new Error('private database error') }),
    });
    await expect(failed.consume('requester', NOW)).rejects.toThrow('rate limiter unavailable');

    const malformed = new SupabaseYoloRateLimiter({
      hmacSecret: 's'.repeat(32),
      rpc: vi.fn().mockResolvedValue({ data: { allowed: true }, error: null }),
    });
    await expect(malformed.consume('requester', NOW)).rejects.toThrow('rate limiter unavailable');
  });
});
