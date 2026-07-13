import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { requireOwner, helpers, rpc } = vi.hoisted(() => ({
  requireOwner: vi.fn(),
  helpers: { loadActiveSetId: vi.fn(), requireApprovedLabelerTarget: vi.fn() },
  rpc: vi.fn(),
}));

vi.mock('@/lib/labelingAccess', () => ({ requireOwner }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));
vi.mock('../../../_helpers', () => helpers);

import { POST } from './route';

function post(userId = 'u2') {
  return POST(
    new NextRequest('https://label.tera-ai.uk/x', {
      method: 'POST',
      headers: { authorization: 'Bearer t' },
    }),
    { params: { userId } },
  );
}

describe('POST tutorial reset (owner)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireOwner.mockResolvedValue({ ok: true, userId: 'owner-1' });
    helpers.requireApprovedLabelerTarget.mockResolvedValue(null);
    helpers.loadActiveSetId.mockResolvedValue('set1');
    rpc.mockResolvedValue({ data: { current_run_no: 2 }, error: null });
  });

  it('non-owner 는 requireOwner 응답(403), RPC 미호출', async () => {
    requireOwner.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: 'forbidden' }, { status: 403 }),
    });
    expect((await post()).status).toBe(403);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('대상이 labeler 아니면 404, RPC 미호출', async () => {
    helpers.requireApprovedLabelerTarget.mockResolvedValue(
      NextResponse.json({ detail: 'labeler not found' }, { status: 404 }),
    );
    expect((await post()).status).toBe(404);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('active set 없으면 409', async () => {
    helpers.loadActiveSetId.mockResolvedValue(null);
    expect((await post()).status).toBe(409);
  });

  it('valid → fn_reset_tutorial 호출 200', async () => {
    const res = await post('u2');
    expect(res.status).toBe(200);
    expect(rpc).toHaveBeenCalledWith('fn_reset_tutorial', {
      p_set_id: 'set1',
      p_user_id: 'u2',
      p_owner_id: 'owner-1',
    });
  });
});
