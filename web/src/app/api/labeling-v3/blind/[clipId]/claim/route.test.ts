import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { requireProductionLabelingAccess, rpc } = vi.hoisted(() => ({
  requireProductionLabelingAccess: vi.fn(),
  rpc: vi.fn(),
}));
vi.mock('@/lib/labelingAccess', () => ({ requireProductionLabelingAccess }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));

import { POST } from './route';

const CLIP = '11111111-1111-4111-8111-111111111111';
const TOKEN = '33333333-3333-4333-8333-333333333333';
const COHORT = '22222222-2222-4222-8222-222222222222';

function req(body: unknown) {
  return new NextRequest(`https://label.tera-ai.uk/api/labeling-v3/blind/${CLIP}/claim`, {
    method: 'POST',
    body: JSON.stringify(body),
    headers: { 'content-type': 'application/json' },
  });
}

describe('POST /api/labeling-v3/blind/[clipId]/claim', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireProductionLabelingAccess.mockResolvedValue({ ok: true, userId: 'labeler-1', isOwner: false });
    rpc.mockResolvedValue({ data: [{ lease_token: TOKEN, lease_expires_at: '2026-07-22T00:30:00Z' }], error: null });
  });

  it('401 passthrough, 403 owner', async () => {
    requireProductionLabelingAccess.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: 'x' }, { status: 401 }),
    });
    expect((await POST(req({ lease_token: TOKEN }), { params: { clipId: CLIP } })).status).toBe(401);
    requireProductionLabelingAccess.mockResolvedValue({ ok: true, userId: 'owner', isOwner: true });
    expect((await POST(req({ lease_token: TOKEN }), { params: { clipId: CLIP } })).status).toBe(403);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('rejects unknown body keys and forged reviewer/group', async () => {
    const res = await POST(
      req({ lease_token: TOKEN, reviewer_id: 'forged', group_id: 'g' }),
      { params: { clipId: CLIP } },
    );
    expect(res.status).toBe(400);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('derives reviewer from bearer and never echoes the lease token', async () => {
    const res = await POST(req({ lease_token: TOKEN }), { params: { clipId: CLIP } });
    expect(res.status).toBe(200);
    const args = rpc.mock.calls[0][1];
    expect(args.p_reviewer_id).toBe('labeler-1');
    expect(args.p_new_token).toBe(TOKEN);
    const body = await res.json();
    expect(body.lease_expires_at).toBe('2026-07-22T00:30:00Z');
    // lease token 은 응답에 없어야 한다(설계 §92).
    expect(JSON.stringify(body)).not.toContain(TOKEN);
  });

  it('same token renews (passes existing token = new token)', async () => {
    await POST(req({ lease_token: TOKEN }), { params: { clipId: CLIP } });
    const args = rpc.mock.calls[0][1];
    expect(args.p_existing_token).toBe(TOKEN);
  });

  it('maps another active tab (PT423) to 409 slot_in_use', async () => {
    rpc.mockResolvedValue({ data: null, error: { code: 'PT423', message: 'slot_in_use raw' } });
    const res = await POST(req({ lease_token: TOKEN }), { params: { clipId: CLIP } });
    expect(res.status).toBe(409);
    const body = await res.json();
    expect(body.code).toBe('slot_in_use');
    expect(JSON.stringify(body)).not.toContain('raw');
  });

  it('rejects an invalid lease token before RPC', async () => {
    const res = await POST(req({ lease_token: 'not-a-uuid' }), { params: { clipId: CLIP } });
    expect(res.status).toBe(400);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('binds canary cohort scope when provided', async () => {
    await POST(req({ lease_token: TOKEN, cohort_id: COHORT }), { params: { clipId: CLIP } });
    const args = rpc.mock.calls[0][1];
    expect(args.p_cohort_kind).toBe('canary');
    expect(args.p_cohort_id).toBe(COHORT);
  });
});
