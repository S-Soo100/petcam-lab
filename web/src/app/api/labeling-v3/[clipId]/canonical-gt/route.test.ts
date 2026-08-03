import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { requireOwner, rpc, from } = vi.hoisted(() => ({
  requireOwner: vi.fn(), rpc: vi.fn(), from: vi.fn(),
}));
vi.mock('@/lib/labelingAccess', () => ({ requireOwner }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc, from } }));

import { GET, POST } from './route';

const CLIP = '11111111-1111-4111-8111-111111111111';
const REV = '22222222-2222-4222-8222-222222222222';
const GT = { visibility: 'visible', primary_action: 'moving', observed_actions: ['moving'], segments: [{ action: 'moving', start_sec: 0, end_sec: 5 }], target: 'none', human_confidence: 'certain', context_tags: ['ir'], activity_intensity: null, highlight_recommendation: 'include', enrichment_object: 'none', interaction_types: [], note: null };

function request(method = 'GET', body?: unknown) {
  return new NextRequest(`https://label.tera-ai.uk/api/labeling-v3/${CLIP}/canonical-gt`, {
    method, body: body ? JSON.stringify(body) : undefined,
  });
}

describe('canonical GT owner route', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    delete process.env.LABELING_CANONICAL_GT_OWNER_WRITE_ENABLED;
    process.env.LABELING_CANONICAL_GT_OWNER_READ_ENABLED = 'true';
    requireOwner.mockResolvedValue({ ok: true, userId: '33333333-3333-4333-8333-333333333333' });
  });

  it('GET read flag off면 DB 호출 없이 404', async () => {
    delete process.env.LABELING_CANONICAL_GT_OWNER_READ_ENABLED;
    const res = await GET(request(), { params: { clipId: CLIP } });
    expect(res.status).toBe(404);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('GET은 owner RPC 결과를 allowlist 계약으로 반환한다', async () => {
    rpc.mockResolvedValue({ data: { status: 'final', revision_id: REV, decision: 'label', gt: GT, source_type: 'blind_consensus', updated_at: '2026-08-04T00:00:00Z', reviewer_id: 'hidden' }, error: null });
    const res = await GET(request(), { params: { clipId: CLIP } });
    expect(res.status).toBe(200);
    expect(rpc).toHaveBeenCalledWith('fn_get_motion_clip_canonical_gt', { p_clip_id: CLIP, p_actor_id: '33333333-3333-4333-8333-333333333333' });
    expect(JSON.stringify(await res.json())).not.toContain('reviewer');
  });

  it('POST write flag off면 DB 호출 없이 404', async () => {
    const res = await POST(request('POST', { expectedRevisionId: REV, gt: GT, reason: '충분히 긴 보정 사유입니다.' }), { params: { clipId: CLIP } });
    expect(res.status).toBe(404);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('POST는 duration 검증 후 optimistic revision으로 override한다', async () => {
    process.env.LABELING_CANONICAL_GT_OWNER_WRITE_ENABLED = 'true';
    const chain: Record<string, unknown> = {};
    for (const m of ['select', 'eq', 'limit']) chain[m] = vi.fn(() => chain);
    (chain as { then: unknown }).then = (resolve: (v: unknown) => unknown) => resolve({ data: [{ duration_sec: 60 }], error: null });
    from.mockReturnValue(chain);
    rpc.mockResolvedValue({ data: { revision_id: '44444444-4444-4444-8444-444444444444', status: 'final' }, error: null });
    const res = await POST(request('POST', { expectedRevisionId: REV, gt: GT, reason: '충분히 긴 보정 사유입니다.' }), { params: { clipId: CLIP } });
    expect(res.status).toBe(200);
    expect(rpc).toHaveBeenCalledWith('fn_override_motion_clip_canonical_gt', expect.objectContaining({ p_expected_revision_id: REV, p_new_gt: GT }));
  });

  it('stale write는 원문 없이 409', async () => {
    process.env.LABELING_CANONICAL_GT_OWNER_WRITE_ENABLED = 'true';
    const chain: Record<string, unknown> = {};
    for (const m of ['select', 'eq', 'limit']) chain[m] = vi.fn(() => chain);
    (chain as { then: unknown }).then = (resolve: (v: unknown) => unknown) => resolve({ data: [{ duration_sec: 60 }], error: null });
    from.mockReturnValue(chain);
    rpc.mockResolvedValue({ data: null, error: { code: 'PT409', message: 'raw expected revision' } });
    const res = await POST(request('POST', { expectedRevisionId: REV, gt: GT, reason: '충분히 긴 보정 사유입니다.' }), { params: { clipId: CLIP } });
    expect(res.status).toBe(409);
    expect(JSON.stringify(await res.json())).not.toContain('raw');
  });
});
