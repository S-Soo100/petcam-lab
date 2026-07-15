import { describe, expect, it, vi } from 'vitest';

// supabaseAdmin 은 client 생성 시 env 를 읽으므로 mock 한다(이 테스트는 순수 응답만 검증).
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: {} }));

import { databaseError } from './_helpers';

describe('databaseError — DB 원문 비노출(설계 §7)', () => {
  it('returns a generic 502 without leaking the raw Supabase message or table', async () => {
    const res = databaseError(
      new Error('relation "clip_labeling_triage" does not exist (PT409 trigger)'),
    );
    expect(res.status).toBe(502);
    const body = await res.json();
    const json = JSON.stringify(body);
    expect(json).not.toContain('clip_labeling_triage');
    expect(json).not.toContain('relation');
    expect(json).not.toContain('PT409');
    expect(typeof body.detail).toBe('string');
  });
});
