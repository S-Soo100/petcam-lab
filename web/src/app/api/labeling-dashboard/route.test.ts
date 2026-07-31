import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { requireLabelingAccess, rpc } = vi.hoisted(() => ({
  requireLabelingAccess: vi.fn(),
  rpc: vi.fn(),
}));
vi.mock('@/lib/labelingAccess', () => ({ requireLabelingAccess }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));

import { GET } from './route';

function req() {
  return new NextRequest('https://label.tera-ai.uk/api/labeling-dashboard', {
    headers: { Authorization: 'Bearer token' },
  });
}

describe('GET /api/labeling-dashboard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    process.env.DEV_USER_ID = 'owner-id';
    requireLabelingAccess.mockResolvedValue({ ok: true, userId: 'labeler-id', isOwner: false });
    rpc.mockResolvedValue({
      data: {
        video_record_count: 100,
        playable_video_count: 90,
        gt_labeled_video_count: 10,
        behavior_counts: { moving: 10 },
        generated_at: '2026-07-31T10:00:00Z',
      },
      error: null,
    });
  });

  it('owner와 활성 labeler 공통 guard를 사용하고 owner 기준 GT를 집계한다', async () => {
    const res = await GET(req());
    expect(res.status).toBe(200);
    expect(rpc).toHaveBeenCalledWith('fn_get_labeling_data_dashboard', {
      p_owner_id: 'owner-id',
    });
    expect((await res.json()).gt_labeled_video_count).toBe(10);
  });

  it('미승인/토큰 오류를 그대로 차단한다', async () => {
    requireLabelingAccess.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: 'forbidden' }, { status: 403 }),
    });
    expect((await GET(req())).status).toBe(403);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('owner id 누락과 DB 오류를 실패로 드러낸다', async () => {
    delete process.env.DEV_USER_ID;
    expect((await GET(req())).status).toBe(503);
    process.env.DEV_USER_ID = 'owner-id';
    rpc.mockResolvedValue({ data: null, error: { message: 'down' } });
    expect((await GET(req())).status).toBe(502);
  });
});
