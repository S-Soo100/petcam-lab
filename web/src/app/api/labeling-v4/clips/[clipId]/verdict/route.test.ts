import { NextRequest } from 'next/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { loadV4ClipAccess, rpc } = vi.hoisted(() => ({ loadV4ClipAccess: vi.fn(), rpc: vi.fn() }));
vi.mock('../../../_access', () => ({ loadV4ClipAccess }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));
vi.mock('@/lib/labelingV3Server', () => ({
  readGmeActiveContract: () => ({ engine_schema_version: 'gme-shadow-v1', algorithm_version: 'gme-motion-v1', detector_identity: 'a'.repeat(64) }),
}));

import { POST } from './route';

const CLIP = '00000000-0000-4000-8000-000000000001';
const post = (body: unknown) => new NextRequest(`https://label.tera-ai.uk/api/labeling-v4/clips/${CLIP}/verdict`, { method: 'POST', body: JSON.stringify(body), headers: { 'content-type': 'application/json' } });

beforeEach(() => {
  vi.clearAllMocks();
  loadV4ClipAccess.mockResolvedValue({ ok: true, userId: 'u1', isOwner: false, clip: { id: CLIP } });
  rpc.mockResolvedValue({ data: [{ verdict_id: '50000000-0000-4000-8000-000000000001', initial: true, changed: true, rule_version: 'hl-rule-v0' }], error: null });
});

describe('POST /api/labeling-v4/clips/[clipId]/verdict', () => {
  it('라벨러 initial 확정을 RPC 에 그대로 넘긴다', async () => {
    const res = await POST(post({ verdict: false, change_reason: 'false_detection' }), { params: { clipId: CLIP } });
    expect(res.status).toBe(200);
    expect(rpc).toHaveBeenCalledWith('fn_submit_highlight_verdict', {
      p_clip_id: CLIP, p_reviewer_id: 'u1', p_is_owner: false, p_verdict: false, p_kind: 'initial', p_change_reason: 'false_detection',
      p_engine_schema_version: 'gme-shadow-v1', p_algorithm_version: 'gme-motion-v1', p_detector_identity: 'a'.repeat(64),
    });
    expect(await res.json()).toEqual({ verdict_id: '50000000-0000-4000-8000-000000000001', initial: true, changed: true, rule_version: 'hl-rule-v0' });
  });
  it('verdict 가 boolean 이 아니면 400, RPC 호출 없음', async () => {
    expect((await POST(post({ verdict: 'yes' }), { params: { clipId: CLIP } })).status).toBe(400);
    expect(rpc).not.toHaveBeenCalled();
  });
  it('모르는 change_reason 은 400', async () => {
    expect((await POST(post({ verdict: true, change_reason: 'lol' }), { params: { clipId: CLIP } })).status).toBe(400);
  });
  it('라벨러의 correction 은 403', async () => {
    expect((await POST(post({ verdict: true, kind: 'correction' }), { params: { clipId: CLIP } })).status).toBe(403);
    expect(rpc).not.toHaveBeenCalled();
  });
  it('PT409 는 409 already_decided', async () => {
    rpc.mockResolvedValue({ data: null, error: { code: 'PT409' } });
    const res = await POST(post({ verdict: true }), { params: { clipId: CLIP } });
    expect(res.status).toBe(409);
    expect((await res.json()).code).toBe('already_decided');
  });
});
