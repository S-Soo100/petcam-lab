import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { requireOwner, rpc } = vi.hoisted(() => ({ requireOwner: vi.fn(), rpc: vi.fn() }));
vi.mock('@/lib/labelingAccess', () => ({ requireOwner }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));

import { POST } from './route';

const PAIR = '11111111-1111-4111-8111-111111111111';
function req(decision: unknown) {
  return new NextRequest(`https://label.tera-ai.uk/api/rba-boundary/pairs/${PAIR}/eligibility`, {
    method: 'POST', body: JSON.stringify({ decision }), headers: { 'content-type': 'application/json' },
  });
}

describe('POST boundary eligibility', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireOwner.mockResolvedValue({ ok: true, userId: 'owner-id' });
    rpc.mockResolvedValue({ data: { submitted: true, completed: 1 }, error: null });
  });

  it('Owner bearer id와 자격 판정만 RPC에 보낸다', async () => {
    const res = await POST(req('left_gecko_absent'), { params: { pairId: PAIR } });
    expect(res.status).toBe(200);
    expect(rpc).toHaveBeenCalledWith('fn_submit_rba_boundary_eligibility', {
      p_owner_id: 'owner-id', p_pair_id: PAIR, p_decision: 'left_gecko_absent',
    });
  });

  it('peer와 잘못된 판정은 RPC 전에 막는다', async () => {
    expect((await POST(req('uncertain'), { params: { pairId: PAIR } })).status).toBe(400);
    requireOwner.mockResolvedValue({
      ok: false, response: NextResponse.json({ detail: 'forbidden' }, { status: 403 }),
    });
    expect((await POST(req('eligible'), { params: { pairId: PAIR } })).status).toBe(403);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('immutable 재제출은 409다', async () => {
    rpc.mockResolvedValue({ data: null, error: { code: 'PT410', message: 'already_submitted' } });
    expect((await POST(req('eligible'), { params: { pairId: PAIR } })).status).toBe(409);
  });
});
