import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

const { requireOwner, rpc } = vi.hoisted(() => ({ requireOwner: vi.fn(), rpc: vi.fn() }));
vi.mock('@/lib/labelingAccess', () => ({ requireOwner }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));

import { POST } from './route';

const PAIR = '11111111-1111-4111-8111-111111111111';
function req(body: unknown) {
  return new NextRequest('https://x/api/rba-boundary/conflicts/x/resolve', {
    method: 'POST', body: JSON.stringify(body), headers: { 'content-type': 'application/json' },
  });
}

describe('POST boundary resolve', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireOwner.mockResolvedValue({ ok: true, userId: 'owner-id' });
    rpc.mockResolvedValue({ data: { resolved: true }, error: null });
  });

  it('owner id와 필수 이유를 RPC에 보낸다', async () => {
    const res = await POST(req({ final_decision: 'different_event', reason: '장면이 끊겨 보여' }), {
      params: { pairId: PAIR },
    });
    expect(res.status).toBe(200);
    expect(rpc).toHaveBeenCalledWith('fn_resolve_rba_boundary_conflict', {
      p_owner_id: 'owner-id', p_pair_id: PAIR,
      p_final_decision: 'different_event', p_reason: '장면이 끊겨 보여',
    });
  });

  it('짧은 이유는 RPC 전에 막는다', async () => {
    expect((await POST(req({ final_decision: 'same_event', reason: 'x' }), {
      params: { pairId: PAIR },
    })).status).toBe(400);
    expect(rpc).not.toHaveBeenCalled();
  });
});
