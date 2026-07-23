import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { requireOwner, rpc } = vi.hoisted(() => ({ requireOwner: vi.fn(), rpc: vi.fn() }));
vi.mock('@/lib/labelingAccess', () => ({ requireOwner }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));

import { GET } from './route';

const CLIP = '11111111-1111-4111-8111-111111111111';
function req(qs = '') {
  return new NextRequest(`https://label.tera-ai.uk/api/labeling-v3/blind/owner/conflicts${qs}`);
}

describe('GET owner/conflicts', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireOwner.mockResolvedValue({ ok: true, userId: 'owner' });
    rpc.mockResolvedValue({
      data: [{ clip_id: CLIP, camera_name: '2번', started_at: 't', differing_fields: ['primary_action'], updated_at: '2026-07-22T00:00:00Z' }],
      error: null,
    });
  });

  it('403 for a labeler (requireOwner gate)', async () => {
    requireOwner.mockResolvedValue({ ok: false, response: NextResponse.json({ detail: 'forbidden' }, { status: 403 }) });
    expect((await GET(req())).status).toBe(403);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('lists conflicts via the conflict-only RPC', async () => {
    const res = await GET(req());
    expect(res.status).toBe(200);
    expect(rpc.mock.calls[0][0]).toBe('fn_list_motion_blind_conflicts');
    const body = await res.json();
    expect(body.items[0].id).toBe(CLIP);
    expect(body.items[0].differing_fields).toEqual(['primary_action']);
  });

  it('rejects a malformed cursor before RPC', async () => {
    const res = await GET(req('?cursor=%%%bad'));
    expect(res.status).toBe(400);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('maps unknown DB error to 502 without raw text', async () => {
    rpc.mockResolvedValue({ data: null, error: { code: '08006', message: 'motion_clip_consensus lost' } });
    const res = await GET(req());
    expect(res.status).toBe(502);
    expect(JSON.stringify(await res.json())).not.toContain('motion_clip_consensus');
  });
});
