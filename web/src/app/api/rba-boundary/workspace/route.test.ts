import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { requireLabelingAccess, rpc } = vi.hoisted(() => ({
  requireLabelingAccess: vi.fn(),
  rpc: vi.fn(),
}));
vi.mock('@/lib/labelingAccess', () => ({ requireLabelingAccess }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));

import { GET } from './route';

const request = new NextRequest('https://label.tera-ai.uk/api/rba-boundary/workspace');

describe('GET /api/rba-boundary/workspace', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireLabelingAccess.mockResolvedValue({ ok: true, userId: 'peer-id', isOwner: false });
    rpc.mockResolvedValue({
      data: { enabled: false, reviewer_role: null, split: null, total: 0, completed: 0, next_pair: null },
      error: null,
    });
  });

  it('활성 팀원 guard 뒤 bearer user id로 assignment workspace를 읽는다', async () => {
    const res = await GET(request);
    expect(res.status).toBe(200);
    expect(rpc).toHaveBeenCalledWith('fn_get_rba_boundary_workspace', {
      p_reviewer_id: 'peer-id',
    });
  });

  it('권한 회수된 사용자는 assignment RPC 전에 차단한다', async () => {
    requireLabelingAccess.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: 'forbidden' }, { status: 403 }),
    });
    expect((await GET(request)).status).toBe(403);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('DB 오류를 raw message 없이 502로 반환한다', async () => {
    rpc.mockResolvedValue({ data: null, error: { message: 'secret table name' } });
    const res = await GET(request);
    expect(res.status).toBe(502);
    expect(JSON.stringify(await res.json())).not.toContain('secret table name');
  });
});
