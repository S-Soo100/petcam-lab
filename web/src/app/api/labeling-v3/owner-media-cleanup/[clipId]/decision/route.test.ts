import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { requireOwner, rpc } = vi.hoisted(() => ({ requireOwner: vi.fn(), rpc: vi.fn() }));
vi.mock('@/lib/labelingAccess', () => ({ requireOwner }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));

import { POST } from './route';

const CLIP = '11111111-1111-4111-8111-111111111111';
function req(decision: string) {
  return new NextRequest(`https://label.tera-ai.uk/api/labeling-v3/owner-media-cleanup/${CLIP}/decision`, {
    method: 'POST', body: JSON.stringify({ decision }),
  });
}

describe('POST owner-media-cleanup decision', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireOwner.mockResolvedValue({ ok: true, userId: 'owner-id' });
    rpc.mockResolvedValue({ data: { recorded: true }, error: null });
  });

  it('허용된 네 결정만 immutable RPC로 보낸다', async () => {
    for (const decision of ['keep', 'delete_gecko_absent', 'delete_no_activity', 'uncertain']) {
      const res = await POST(req(decision), { params: { clipId: CLIP } });
      expect(res.status).toBe(200);
    }
    expect(rpc).toHaveBeenCalledTimes(4);
    expect(rpc.mock.calls[0]).toEqual(['fn_decide_rba_owner_media_cleanup_v1', {
      p_owner_id: 'owner-id', p_clip_id: CLIP, p_decision: 'keep', p_reason: null,
    }]);
  });

  it('알 수 없는 결정은 DB 전에 400', async () => {
    const res = await POST(req('auto_delete'), { params: { clipId: CLIP } });
    expect(res.status).toBe(400);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('비-owner는 DB 접근 0회', async () => {
    requireOwner.mockResolvedValue({ ok: false, response: NextResponse.json({}, { status: 403 }) });
    const res = await POST(req('keep'), { params: { clipId: CLIP } });
    expect(res.status).toBe(403);
    expect(rpc).not.toHaveBeenCalled();
  });
});
