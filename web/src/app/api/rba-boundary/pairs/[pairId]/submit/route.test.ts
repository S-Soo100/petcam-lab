import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { requireLabelingAccess, rpc } = vi.hoisted(() => ({
  requireLabelingAccess: vi.fn(),
  rpc: vi.fn(),
}));
vi.mock('@/lib/labelingAccess', () => ({ requireLabelingAccess }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));

import { POST } from './route';

const PAIR = '11111111-1111-4111-8111-111111111111';
function req(body: unknown) {
  return new NextRequest(`https://label.tera-ai.uk/api/rba-boundary/pairs/${PAIR}/submit`, {
    method: 'POST',
    body: JSON.stringify(body),
    headers: { 'content-type': 'application/json' },
  });
}

describe('POST boundary submit', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireLabelingAccess.mockResolvedValue({ ok: true, userId: 'peer-id', isOwner: false });
    rpc.mockResolvedValue({ data: { submitted: true, pair_id: PAIR }, error: null });
  });

  it('reviewer id를 body가 아니라 bearer guard에서만 가져온다', async () => {
    const res = await POST(req({ decision: 'same_event', reviewer_id: 'attacker' }), {
      params: { pairId: PAIR },
    });
    expect(res.status).toBe(200);
    expect(rpc).toHaveBeenCalledWith('fn_submit_rba_boundary_decision', {
      p_reviewer_id: 'peer-id',
      p_pair_id: PAIR,
      p_decision: 'same_event',
    });
    expect(JSON.stringify(rpc.mock.calls[0])).not.toContain('attacker');
  });

  it('허용되지 않은 decision과 잘못된 UUID는 RPC 전에 막는다', async () => {
    expect((await POST(req({ decision: 'moving' }), { params: { pairId: PAIR } })).status).toBe(400);
    expect((await POST(req({ decision: 'same_event' }), { params: { pairId: 'bad' } })).status).toBe(400);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('권한 회수 사용자는 assignment RPC 전에 차단한다', async () => {
    requireLabelingAccess.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: 'forbidden' }, { status: 403 }),
    });
    expect((await POST(req({ decision: 'same_event' }), { params: { pairId: PAIR } })).status).toBe(403);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('immutable 재제출은 409로 반환한다', async () => {
    rpc.mockResolvedValue({ data: null, error: { code: 'PT410', message: 'already_submitted' } });
    const res = await POST(req({ decision: 'same_event' }), { params: { pairId: PAIR } });
    expect(res.status).toBe(409);
  });
});
