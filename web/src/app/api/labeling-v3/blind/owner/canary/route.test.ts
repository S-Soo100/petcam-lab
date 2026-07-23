import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { requireOwner, rpc } = vi.hoisted(() => ({ requireOwner: vi.fn(), rpc: vi.fn() }));
vi.mock('@/lib/labelingAccess', () => ({ requireOwner }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));

import { POST } from './route';

const CLIP = '11111111-1111-4111-8111-111111111111';
const U1 = 'aaaaaaaa-1111-4111-8111-111111111111';
const U2 = 'bbbbbbbb-1111-4111-8111-111111111111';
const GROUP = 'dddddddd-1111-4111-8111-111111111111';
const COHORT = 'eeeeeeee-1111-4111-8111-111111111111';

function req(body: unknown) {
  return new NextRequest('https://label.tera-ai.uk/api/labeling-v3/blind/owner/canary', {
    method: 'POST',
    body: JSON.stringify(body),
    headers: { 'content-type': 'application/json' },
  });
}

describe('POST owner/canary', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireOwner.mockResolvedValue({ ok: true, userId: 'owner' });
    rpc.mockResolvedValue({ data: COHORT, error: null });
  });

  it('403 for a labeler', async () => {
    requireOwner.mockResolvedValue({ ok: false, response: NextResponse.json({ detail: 'forbidden' }, { status: 403 }) });
    expect((await POST(req({ action: 'create', group_id: GROUP, clip_ids: [CLIP], reviewer_ids: [U1, U2] }))).status).toBe(403);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('creates a canary cohort with 1..20 clips and two reviewers', async () => {
    const res = await POST(req({ action: 'create', group_id: GROUP, clip_ids: [CLIP], reviewer_ids: [U1, U2], label: '12건 검증' }));
    expect(res.status).toBe(200);
    const args = rpc.mock.calls[0][1];
    expect(args.p_action).toBe('create');
    expect(args.p_clip_ids).toEqual([CLIP]);
    expect(args.p_reviewer_ids).toEqual([U1, U2]);
    expect((await res.json()).cohort_id).toBe(COHORT);
  });

  it('rejects an over-20 clip list before RPC', async () => {
    const clips = Array.from({ length: 21 }, (_, i) => `${String(i).padStart(8, '0')}-1111-4111-8111-111111111111`);
    const res = await POST(req({ action: 'create', group_id: GROUP, clip_ids: clips, reviewer_ids: [U1, U2] }));
    expect(res.status).toBe(400);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('closing only changes cohort status (no clip/submission delete)', async () => {
    await POST(req({ action: 'close', cohort_id: COHORT }));
    const args = rpc.mock.calls[0][1];
    expect(args.p_action).toBe('close');
    expect(args.p_cohort_id).toBe(COHORT);
    expect(args.p_clip_ids).toBeNull();
  });

  it('closing an already-closed cohort (PT427) -> 410', async () => {
    rpc.mockResolvedValue({ data: null, error: { code: 'PT427' } });
    const res = await POST(req({ action: 'close', cohort_id: COHORT }));
    expect(res.status).toBe(410);
    expect((await res.json()).code).toBe('cohort_closed');
  });
});
