import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

const { requireOwner, rpc } = vi.hoisted(() => ({ requireOwner: vi.fn(), rpc: vi.fn() }));
vi.mock('@/lib/labelingAccess', () => ({ requireOwner }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));

import { POST } from './route';

const CLIP = '11111111-1111-4111-8111-111111111111';
function req(body: unknown) {
  return new NextRequest(`https://label.tera-ai.uk/api/labeling-v3/${CLIP}/canonical-gt/reconcile`, { method: 'POST', body: JSON.stringify(body) });
}

describe('canonical GT reconcile route', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    process.env.LABELING_CANONICAL_GT_OWNER_WRITE_ENABLED = 'true';
    requireOwner.mockResolvedValue({ ok: true, userId: '33333333-3333-4333-8333-333333333333' });
  });

  it('consensus/direct 선택은 peer identity 없이 RPC로 확정한다', async () => {
    rpc.mockResolvedValue({ data: { revision_id: '44444444-4444-4444-8444-444444444444' }, error: null });
    const res = await POST(req({ expectedHeadRevisionId: null, selectedSource: 'consensus', reason: '교차검수 결과를 기준으로 확정합니다.' }), { params: { clipId: CLIP } });
    expect(res.status).toBe(200);
    expect(rpc).toHaveBeenCalledWith('fn_resolve_motion_clip_gt_reconciliation', expect.objectContaining({ p_selected_source: 'consensus', p_new_gt: null }));
  });

  it('허용되지 않은 선택은 DB 호출 없이 400', async () => {
    const res = await POST(req({ expectedHeadRevisionId: null, selectedSource: 'reviewer-a', reason: '충분히 긴 확정 사유입니다.' }), { params: { clipId: CLIP } });
    expect(res.status).toBe(400);
    expect(rpc).not.toHaveBeenCalled();
  });
});
