import { NextRequest } from 'next/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { loadV4ClipAccess, rpc } = vi.hoisted(() => ({ loadV4ClipAccess: vi.fn(), rpc: vi.fn() }));
vi.mock('../../../_access', () => ({ loadV4ClipAccess, resolveReviewerName: ({ displayName }: { displayName: string | null }) => displayName ?? '라벨러' }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));

import { POST } from './route';

const CLIP = '00000000-0000-4000-8000-000000000001';
const USER = '30000000-0000-4000-8000-000000000001';
const post = (body: unknown) => POST(new NextRequest(`https://label.tera-ai.uk/api/labeling-v4/clips/${CLIP}/behavior-flag`, { method: 'POST', body: JSON.stringify(body) }), { params: { clipId: CLIP } });

beforeEach(() => {
  vi.clearAllMocks();
  loadV4ClipAccess.mockResolvedValue({ ok: true, userId: USER, isOwner: false, clip: { id: CLIP } });
});

describe('POST /api/labeling-v4/clips/[clipId]/behavior-flag', () => {
  it('체크하면 RPC 에 사용자·owner 여부를 넘기고 표시명만 돌려준다', async () => {
    rpc.mockResolvedValue({ data: [{ flagged: true, flagged_by: USER, flagged_by_display_name: '김라벨', flagged_at: '2026-09-08T04:00:00Z' }], error: null });
    const res = await post({ flagged: true });
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ flagged: true, flagged_by_name: '김라벨', flagged_at: '2026-09-08T04:00:00Z' });
    expect(rpc).toHaveBeenCalledWith('fn_set_motion_clip_behavior_flag', { p_clip_id: CLIP, p_user_id: USER, p_is_owner: false, p_flagged: true });
    expect(JSON.stringify(await post({ flagged: true }).then((r) => r.json()))).not.toContain(USER);
  });
  it('해제 결과는 flagged=false', async () => {
    rpc.mockResolvedValue({ data: [{ flagged: false, flagged_by: null, flagged_by_display_name: null, flagged_at: null }], error: null });
    expect(await (await post({ flagged: false })).json()).toEqual({ flagged: false, flagged_by_name: null, flagged_at: null });
  });
  it('남이 체크한 걸 라벨러가 해제하면 DB PT403 → 403', async () => {
    rpc.mockResolvedValue({ data: null, error: { code: 'PT403', message: 'only the flagger or owner can unflag' } });
    const res = await post({ flagged: false });
    expect(res.status).toBe(403);
    expect((await res.json()).code).toBe('forbidden');
  });
  it('flagged 가 boolean 이 아니면 DB 전 400', async () => {
    expect((await post({ flagged: 'yes' })).status).toBe(400);
    expect(rpc).not.toHaveBeenCalled();
  });
});
