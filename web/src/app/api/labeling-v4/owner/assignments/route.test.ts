import { NextRequest } from 'next/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { requireOwner, rpc } = vi.hoisted(() => ({ requireOwner: vi.fn(), rpc: vi.fn() }));
vi.mock('@/lib/labelingAccess', () => ({ requireOwner }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));

import { GET, PUT } from './route';

const URL = 'https://label.tera-ai.uk/api/labeling-v4/owner/assignments';
const U = '30000000-0000-4000-8000-000000000001';
const C = '40000000-0000-4000-8000-000000000001';

beforeEach(() => {
  vi.clearAllMocks();
  requireOwner.mockResolvedValue({ ok: true, userId: 'owner-1' });
  rpc.mockImplementation(async (name: string) => {
    if (name === 'fn_list_labeling_v4_members') return { data: [{ user_id: U, display_name: '김라벨', camera_ids: [C] }], error: null };
    if (name === 'fn_list_labeling_v4_cameras') return { data: [{ camera_id: C, camera_name: '거실', assigned: false }], error: null };
    if (name === 'fn_set_labeler_camera_assignments') return { data: [{ camera_id: C }], error: null };
    throw new Error(name);
  });
});

describe('owner assignments', () => {
  it('GET 은 멤버+카메라', async () => {
    const body = await (await GET(new NextRequest(URL))).json();
    expect(body.members[0]).toEqual({ user_id: U, display_name: '김라벨', camera_ids: [C] });
    expect(body.cameras[0]).toEqual({ id: C, name: '거실', assigned: false });
  });
  it('PUT 은 배정을 갱신한다', async () => {
    const res = await PUT(new NextRequest(URL, { method: 'PUT', body: JSON.stringify({ user_id: U, camera_ids: [C] }) }));
    expect(res.status).toBe(200);
    expect(rpc).toHaveBeenCalledWith('fn_set_labeler_camera_assignments', { p_user_id: U, p_camera_ids: [C], p_actor_id: 'owner-1' });
    expect(await res.json()).toEqual({ camera_ids: [C] });
  });
  it('uuid 아니면 400', async () => {
    expect((await PUT(new NextRequest(URL, { method: 'PUT', body: JSON.stringify({ user_id: 'x', camera_ids: [] }) }))).status).toBe(400);
  });
});
