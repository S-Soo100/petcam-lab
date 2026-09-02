import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { requireOwner, rpc } = vi.hoisted(() => ({
  requireOwner: vi.fn(),
  rpc: vi.fn(),
}));
vi.mock('@/lib/labelingAccess', () => ({ requireOwner }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));

import { GET } from './route';

describe('GET owner-media-cleanup', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireOwner.mockResolvedValue({ ok: true, userId: 'owner-id' });
  });

  it('비-owner는 DB 접근 0회', async () => {
    requireOwner.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: 'forbidden' }, { status: 403 }),
    });
    const res = await GET(new NextRequest('https://label.tera-ai.uk/api/labeling-v3/owner-media-cleanup'));
    expect(res.status).toBe(403);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('summary와 첫 미결 1건만 공개 필드로 반환', async () => {
    rpc
      .mockResolvedValueOnce({ data: { available: 897, completed: 0, remaining: 897, source_missing: 7 }, error: null })
      .mockResolvedValueOnce({ data: [{
        clip_id: '11111111-1111-4111-8111-111111111111',
        started_at: '2026-07-14T12:00:00Z', duration_sec: 30, camera_name: 'A',
        seed_reason: 'owner_review_pending', state: 'quarantined', has_canonical_gt: false,
        decision: null, r2_key: 'must-not-leak', owner_id: 'must-not-leak',
      }], error: null });
    const res = await GET(new NextRequest('https://label.tera-ai.uk/api/labeling-v3/owner-media-cleanup'));
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.item.clip_id).toBe('11111111-1111-4111-8111-111111111111');
    expect(body.summary.remaining).toBe(897);
    expect(JSON.stringify(body)).not.toContain('must-not-leak');
    expect(rpc.mock.calls[1][1].p_limit).toBe(1);
  });
});
