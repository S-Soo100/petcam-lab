import { afterAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { requireLabelingAccess, rpc } = vi.hoisted(() => ({
  requireLabelingAccess: vi.fn(),
  rpc: vi.fn(),
}));
vi.mock('@/lib/labelingAccess', () => ({ requireLabelingAccess }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));

import { GET } from './route';

const PREV_CANONICAL_ENV = process.env.LABELING_CANONICAL_GT_DASHBOARD_READ_ENABLED;

function req() {
  return new NextRequest('https://label.tera-ai.uk/api/labeling-dashboard', {
    headers: { Authorization: 'Bearer token' },
  });
}

describe('GET /api/labeling-dashboard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    delete process.env.LABELING_CANONICAL_GT_DASHBOARD_READ_ENABLED;
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

  afterAll(() => {
    if (PREV_CANONICAL_ENV === undefined) {
      delete process.env.LABELING_CANONICAL_GT_DASHBOARD_READ_ENABLED;
    } else {
      process.env.LABELING_CANONICAL_GT_DASHBOARD_READ_ENABLED = PREV_CANONICAL_ENV;
    }
  });

  it('owner와 활성 labeler 공통 guard를 사용하고 owner 기준 GT를 집계한다', async () => {
    const res = await GET(req());
    expect(res.status).toBe(200);
    expect(rpc).toHaveBeenCalledWith('fn_get_labeling_data_dashboard', {
      p_owner_id: 'owner-id',
    });
    const body = await res.json();
    expect(body.gt_labeled_video_count).toBe(10);
    expect(body).not.toHaveProperty('gt_revision_digest');
  });

  it('독립 flag가 켜진 경우에만 canonical dashboard RPC를 호출한다', async () => {
    process.env.LABELING_CANONICAL_GT_DASHBOARD_READ_ENABLED = 'true';
    rpc.mockResolvedValue({
      data: {
        video_record_count: 100,
        playable_video_count: 90,
        gt_labeled_video_count: 10,
        behavior_counts: { moving: 10 },
        gt_revision_count: 12,
        gt_revision_digest: 'a'.repeat(64),
        generated_at: '2026-07-31T10:00:00Z',
      },
      error: null,
    });
    const res = await GET(req());
    expect(res.status).toBe(200);
    expect(rpc).toHaveBeenCalledWith('fn_get_labeling_data_dashboard_canonical', {
      p_owner_id: 'owner-id',
    });
    expect(await res.json()).toMatchObject({
      gt_revision_count: 12,
      gt_revision_digest: 'a'.repeat(64),
    });
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
