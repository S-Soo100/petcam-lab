import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { requireOwner, rpc } = vi.hoisted(() => ({
  requireOwner: vi.fn(),
  rpc: vi.fn(),
}));
vi.mock('@/lib/labelingAccess', () => ({ requireOwner }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));

import { GET } from './route';

function req() {
  return new NextRequest('https://label.tera-ai.uk/api/labeling-v3/canonical-gt/health');
}

describe('GET /api/labeling-v3/canonical-gt/health', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    process.env.LABELING_CANONICAL_GT_PROJECTION_ENABLED = 'true';
    requireOwner.mockResolvedValue({ ok: true, userId: 'owner-id' });
    rpc.mockResolvedValue({
      data: {
        healthy: true,
        last_success_at: '2026-08-04T00:00:00Z',
        lag_seconds: 3,
        pending_final_source_count: 1,
        last_error_code: null,
        private_source_id: 'must-not-leak',
      },
      error: null,
    });
  });

  it('projection flag off면 DB 호출 없이 404', async () => {
    delete process.env.LABELING_CANONICAL_GT_PROJECTION_ENABLED;
    const response = await GET(req());
    expect(response.status).toBe(404);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('owner만 projection health 화이트리스트를 본다', async () => {
    const response = await GET(req());
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({
      healthy: true,
      lastSuccessAt: '2026-08-04T00:00:00Z',
      lagSeconds: 3,
      pendingFinalSourceCount: 1,
      lastErrorCode: null,
    });
    expect(rpc).toHaveBeenCalledWith('fn_get_motion_clip_gt_projection_health');
  });

  it('owner가 아니면 DB를 읽지 않는다', async () => {
    requireOwner.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: 'forbidden' }, { status: 403 }),
    });
    expect((await GET(req())).status).toBe(403);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('DB 오류는 일반화된 502다', async () => {
    rpc.mockResolvedValue({ data: null, error: { message: 'private' } });
    const response = await GET(req());
    expect(response.status).toBe(502);
    expect(JSON.stringify(await response.json())).not.toContain('private');
  });
});
