import 'server-only';

import { createHmac } from 'node:crypto';

import { supabaseAdmin } from './supabase';
import type { RateLimiter, RateLimitResult } from './yoloDetectionServer';

type RpcResult = { data: unknown; error: unknown };
type Rpc = (name: string, args: Record<string, unknown>) => PromiseLike<RpcResult>;

function parseResult(value: unknown): RateLimitResult | null {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return null;
  const row = value as Record<string, unknown>;
  if (typeof row.allowed !== 'boolean') return null;
  if (!Number.isInteger(row.retry_after_sec) || (row.retry_after_sec as number) < 0) return null;
  if (row.allowed && row.retry_after_sec !== 0) return null;
  if (!row.allowed && row.retry_after_sec === 0) return null;
  return { allowed: row.allowed, retryAfterSec: row.retry_after_sec as number };
}

export class SupabaseYoloRateLimiter implements RateLimiter {
  readonly scope = 'distributed' as const;
  private readonly hmacSecret: string;
  private readonly rpc: Rpc;

  constructor(config: { hmacSecret: string; rpc?: Rpc }) {
    if (config.hmacSecret.length < 32 || config.hmacSecret.length > 512) {
      throw new Error('invalid YOLO rate-limit HMAC secret');
    }
    this.hmacSecret = config.hmacSecret;
    this.rpc = config.rpc ?? ((name, args) => supabaseAdmin.rpc(name, args) as unknown as PromiseLike<RpcResult>);
  }

  async consume(key: string, nowMs: number): Promise<RateLimitResult> {
    try {
      if (!Number.isFinite(nowMs)) throw new Error('invalid time');
      const keyHash = createHmac('sha256', this.hmacSecret).update(key).digest('hex');
      const { data, error } = await this.rpc('fn_consume_yolo_demo_rate_limit', {
        p_key_hash: keyHash,
        p_now: new Date(nowMs).toISOString(),
        p_limit: 5,
        p_window_sec: 600,
      });
      if (error) throw error;
      const parsed = parseResult(data);
      if (!parsed) throw new Error('invalid RPC result');
      return parsed;
    } catch {
      throw new Error('rate limiter unavailable');
    }
  }
}
