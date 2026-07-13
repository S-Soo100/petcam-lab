import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { requireOwner, rpc } = vi.hoisted(() => ({
  requireOwner: vi.fn(),
  rpc: vi.fn(),
}));

vi.mock('@/lib/labelingAccess', () => ({ requireOwner }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));

import { POST } from './route';

function request(decision: string) {
  return new NextRequest(
    'https://label.tera-ai.uk/api/labeling-team/user-1/decision',
    {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ decision }),
    },
  );
}

describe('POST /api/labeling-team/[userId]/decision', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireOwner.mockResolvedValue({ ok: true, userId: 'owner-user' });
    rpc.mockResolvedValue({
      data: [{ user_id: 'user-1', status: 'approved' }],
      error: null,
    });
  });

  it('returns the owner guard response without calling the RPC', async () => {
    requireOwner.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: 'forbidden' }, { status: 403 }),
    });

    const response = await POST(request('approve'), { params: { userId: 'user-1' } });

    expect(response.status).toBe(403);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('rejects a decision outside the explicit allowlist', async () => {
    const response = await POST(request('delete-account'), {
      params: { userId: 'user-1' },
    });
    expect(response.status).toBe(400);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('passes the owner and target IDs to the atomic review RPC', async () => {
    const response = await POST(request('approve'), { params: { userId: 'user-1' } });

    expect(response.status).toBe(200);
    expect(rpc).toHaveBeenCalledWith('fn_review_labeler_application', {
      p_user_id: 'user-1',
      p_reviewer_id: 'owner-user',
      p_decision: 'approve',
    });
  });
});
