import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { requireOwner, rpc } = vi.hoisted(() => ({ requireOwner: vi.fn(), rpc: vi.fn() }));
vi.mock('@/lib/labelingAccess', () => ({ requireOwner }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));

import { POST } from './route';

const U1 = 'aaaaaaaa-1111-4111-8111-111111111111';
const U2 = 'bbbbbbbb-1111-4111-8111-111111111111';
const CAM = 'cccccccc-1111-4111-8111-111111111111';
const GROUP = 'dddddddd-1111-4111-8111-111111111111';

function req(body: unknown) {
  return new NextRequest('https://label.tera-ai.uk/api/labeling-v3/blind/owner/groups', {
    method: 'POST',
    body: JSON.stringify(body),
    headers: { 'content-type': 'application/json' },
  });
}

describe('POST owner/groups', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireOwner.mockResolvedValue({ ok: true, userId: 'owner' });
    rpc.mockResolvedValue({ data: GROUP, error: null });
  });

  it('403 for a labeler', async () => {
    requireOwner.mockResolvedValue({ ok: false, response: NextResponse.json({ detail: 'forbidden' }, { status: 403 }) });
    expect((await POST(req({ name: 'A그룹', member_ids: [U1, U2], camera_ids: [CAM] }))).status).toBe(403);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('rejects a member list that is not two UUIDs', async () => {
    for (const members of [[U1], [U1, U2, CAM], ['not-a-uuid', U2]]) {
      rpc.mockClear();
      const res = await POST(req({ name: 'A그룹', member_ids: members, camera_ids: [CAM] }));
      expect(res.status).toBe(400);
      expect(rpc).not.toHaveBeenCalled();
    }
  });

  it('rejects email supplied as the persistence key', async () => {
    const res = await POST(req({ name: 'A그룹', member_ids: ['a@gmail.com', U2], camera_ids: [CAM] }));
    expect(res.status).toBe(400);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('passes approved user ids + camera ids to the transaction RPC', async () => {
    const res = await POST(req({ group_id: GROUP, name: 'A그룹', member_ids: [U1, U2], camera_ids: [CAM] }));
    expect(res.status).toBe(200);
    const args = rpc.mock.calls[0][1];
    expect(args.p_actor_id).toBe('owner');
    expect(args.p_member_ids).toEqual([U1, U2]);
    expect(args.p_camera_ids).toEqual([CAM]);
    expect((await res.json()).group_id).toBe(GROUP);
  });

  it('maps group invariant / duplicate camera (PT425) to 409 without raw text', async () => {
    rpc.mockResolvedValue({ data: null, error: { code: 'PT425', message: 'camera active in another group raw' } });
    const res = await POST(req({ name: 'A그룹', member_ids: [U1, U2], camera_ids: [CAM] }));
    expect(res.status).toBe(409);
    const body = await res.json();
    expect(body.code).toBe('group_invariant');
    expect(JSON.stringify(body)).not.toContain('raw');
  });

  it('response never contains email/auth metadata', async () => {
    const res = await POST(req({ name: 'A그룹', member_ids: [U1, U2], camera_ids: [CAM] }));
    const json = JSON.stringify(await res.json());
    expect(json).not.toContain('@');
  });
});
