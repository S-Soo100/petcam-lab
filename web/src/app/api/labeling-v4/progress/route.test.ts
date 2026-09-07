import { NextRequest, NextResponse } from 'next/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { requireLabelingAccess, rpc } = vi.hoisted(() => ({ requireLabelingAccess: vi.fn(), rpc: vi.fn() }));
vi.mock('@/lib/labelingAccess', () => ({ requireLabelingAccess }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));

import { GET } from './route';

const req = () => new NextRequest('https://label.tera-ai.uk/api/labeling-v4/progress');

beforeEach(() => {
  vi.clearAllMocks();
  requireLabelingAccess.mockResolvedValue({ ok: true, userId: 'labeler-1', isOwner: false });
});

describe('GET /api/labeling-v4/progress', () => {
  it('요청자 id 로 RPC 를 부르고 숫자로 정규화한다(mine null 유지)', async () => {
    rpc.mockResolvedValue({ data: { activity_day: '2026-09-08', labeled_today_me: '3', labeled_today_all: 10, unlabeled_all: '250', unlabeled_mine: null }, error: null });
    const body = await (await GET(req())).json();
    expect(rpc).toHaveBeenCalledWith('fn_get_labeling_v4_progress', { p_viewer_id: 'labeler-1' });
    expect(body).toEqual({ activity_day: '2026-09-08', labeled_today_me: 3, labeled_today_all: 10, unlabeled_all: 250, unlabeled_mine: null });
  });
  it('미승인은 가드 응답 그대로, RPC 0회', async () => {
    requireLabelingAccess.mockResolvedValue({ ok: false, response: NextResponse.json({ detail: 'forbidden' }, { status: 403 }) });
    expect((await GET(req())).status).toBe(403);
    expect(rpc).not.toHaveBeenCalled();
  });
});
