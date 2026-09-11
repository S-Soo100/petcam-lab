import { NextRequest } from 'next/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { loadV4ClipAccess, rpc } = vi.hoisted(() => ({ loadV4ClipAccess: vi.fn(), rpc: vi.fn() }));
vi.mock('../../../_access', () => ({ loadV4ClipAccess, resolveReviewerName: ({ displayName }: { displayName: string | null }) => displayName ?? '라벨러' }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));

import { POST } from './route';

const CLIP = '00000000-0000-4000-8000-000000000001';
const USER = '30000000-0000-4000-8000-000000000001';
const post = (body: unknown) => POST(new NextRequest(`https://label.tera-ai.uk/api/labeling-v4/clips/${CLIP}/behavior-flag`, { method: 'POST', body: JSON.stringify(body) }), { params: { clipId: CLIP } });
const row = (kind: string, flagged: boolean) => (flagged
  ? { kind, flagged: true, flagged_by: USER, flagged_by_display_name: '김라벨', flagged_at: '2026-09-08T04:00:00Z' }
  : { kind, flagged: false, flagged_by: null, flagged_by_display_name: null, flagged_at: null });
const rows = (on: string[]) => ['meaningful', 'wheel', 'fall', 'closeup'].map((k) => row(k, on.includes(k)));

beforeEach(() => {
  vi.clearAllMocks();
  loadV4ClipAccess.mockResolvedValue({ ok: true, userId: USER, isOwner: false, clip: { id: CLIP } });
});

describe('POST /api/labeling-v4/clips/[clipId]/behavior-flag (행동 표시 4종)', () => {
  it('kind 로 표시하면 5-인자 RPC 에 사용자·owner 여부·kind 를 넘기고 4종 전체를 표시명만으로 돌려준다', async () => {
    rpc.mockResolvedValue({ data: rows(['wheel']), error: null });
    const res = await post({ kind: 'wheel', flagged: true });
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.wheel).toEqual({ flagged: true, flagged_by_name: '김라벨', flagged_at: '2026-09-08T04:00:00Z' });
    expect(body.meaningful).toEqual({ flagged: false, flagged_by_name: null, flagged_at: null });
    expect(Object.keys(body).sort()).toEqual(['closeup', 'fall', 'meaningful', 'wheel']);
    expect(rpc).toHaveBeenCalledWith('fn_set_motion_clip_behavior_flag', { p_clip_id: CLIP, p_user_id: USER, p_is_owner: false, p_kind: 'wheel', p_flagged: true });
    expect(JSON.stringify(body)).not.toContain(USER);
  });
  it('kind 생략은 meaningful(구버전 호환)', async () => {
    rpc.mockResolvedValue({ data: rows(['meaningful']), error: null });
    expect((await (await post({ flagged: true })).json()).meaningful.flagged).toBe(true);
    expect(rpc).toHaveBeenCalledWith('fn_set_motion_clip_behavior_flag', expect.objectContaining({ p_kind: 'meaningful' }));
  });
  it('남이 표시한 걸 라벨러가 해제하면 DB PT403 → 403', async () => {
    rpc.mockResolvedValue({ data: null, error: { code: 'PT403', message: 'only the flagger or owner can unflag' } });
    const res = await post({ kind: 'fall', flagged: false });
    expect(res.status).toBe(403);
    expect((await res.json()).code).toBe('forbidden');
  });
  it('flagged 가 boolean 아님 / 모르는 kind 는 DB 전 400', async () => {
    expect((await post({ flagged: 'yes' })).status).toBe(400);
    expect((await post({ kind: 'jump', flagged: true })).status).toBe(400);
    expect(rpc).not.toHaveBeenCalled();
  });
});
