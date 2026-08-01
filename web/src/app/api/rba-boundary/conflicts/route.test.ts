import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { requireOwner, rpc } = vi.hoisted(() => ({ requireOwner: vi.fn(), rpc: vi.fn() }));
vi.mock('@/lib/labelingAccess', () => ({ requireOwner }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));

import { GET } from './route';

describe('GET boundary conflicts', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireOwner.mockResolvedValue({ ok: true, userId: 'owner-id' });
    rpc.mockResolvedValue({ data: { ready: false, items: [], total: 0 }, error: null });
  });

  it('owner만 자신의 해결 대기를 읽는다', async () => {
    expect((await GET(new NextRequest('https://x/api/rba-boundary/conflicts'))).status).toBe(200);
    expect(rpc).toHaveBeenCalledWith('fn_list_rba_boundary_conflicts', { p_owner_id: 'owner-id' });
  });

  it('non-owner는 RPC 전에 차단한다', async () => {
    requireOwner.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: 'forbidden' }, { status: 403 }),
    });
    expect((await GET(new NextRequest('https://x/api/rba-boundary/conflicts'))).status).toBe(403);
    expect(rpc).not.toHaveBeenCalled();
  });
});
