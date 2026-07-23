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
const OWN = 'aaaaaaaa-1111-4111-8111-111111111111';
const PEER = 'bbbbbbbb-1111-4111-8111-111111111111';

function req(body: unknown) {
  return new NextRequest(`https://label.tera-ai.uk/api/labeling-v3/blind/${CLIP}/submit`, {
    method: 'POST',
    body: JSON.stringify(body),
    headers: { 'content-type': 'application/json' },
  });
}

const excludeBody = { decision: 'exclude', initial_gt: null, note: null, reason_code: 'gecko_absent', lease_token: TOKEN };

function submitRowNoPeer() {
  return { own_submission_id: OWN, own_digest: 'd-own', is_duplicate: false, peer_present: false };
}
function submitRowWithPeer(overrides: Record<string, unknown> = {}) {
  return {
    own_submission_id: OWN,
    own_digest: 'd-own',
    is_duplicate: false,
    peer_present: true,
    peer_submission_id: PEER,
    peer_digest: 'd-peer',
    peer_decision: 'exclude',
    peer_reason_code: 'media_error',
    peer_initial_gt: null,
    peer_note: 'peer-secret-note',
    ...overrides,
  };
}

function mockRpc(handlers: Record<string, () => unknown>) {
  rpc.mockImplementation((fn: string) => Promise.resolve(handlers[fn]?.() ?? { data: null, error: null }));
}

describe('POST /api/labeling-v3/blind/[clipId]/submit', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireProductionLabelingAccess.mockResolvedValue({ ok: true, userId: 'labeler-1', isOwner: false });
  });

  it('401 passthrough, 403 owner', async () => {
    requireProductionLabelingAccess.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: 'x' }, { status: 401 }),
    });
    expect((await POST(req(excludeBody), { params: { clipId: CLIP } })).status).toBe(401);
    requireProductionLabelingAccess.mockResolvedValue({ ok: true, userId: 'owner', isOwner: true });
    expect((await POST(req(excludeBody), { params: { clipId: CLIP } })).status).toBe(403);
  });

  it('does not accept reviewer/group/peer fields from body', async () => {
    const res = await POST(
      req({ ...excludeBody, reviewer_id: 'forged', peer_decision: 'label' }),
      { params: { clipId: CLIP } },
    );
    expect(res.status).toBe(400);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('rejects label without valid initial_gt before RPC', async () => {
    const res = await POST(
      req({ decision: 'label', initial_gt: null, note: null, reason_code: 'behavior_data', lease_token: TOKEN }),
      { params: { clipId: CLIP } },
    );
    expect(res.status).toBe(400);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('rejects exclude/hold carrying an initial_gt before RPC', async () => {
    const res = await POST(
      req({ decision: 'exclude', initial_gt: { visibility: 'absent' }, note: null, reason_code: 'gecko_absent', lease_token: TOKEN }),
      { params: { clipId: CLIP } },
    );
    expect(res.status).toBe(400);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('rejects an oversized body before parsing', async () => {
    const big = 'x'.repeat(70 * 1024);
    const r = new NextRequest(`https://label.tera-ai.uk/api/labeling-v3/blind/${CLIP}/submit`, {
      method: 'POST',
      body: JSON.stringify({ ...excludeBody, note: big }),
      headers: { 'content-type': 'application/json' },
    });
    const res = await POST(r, { params: { clipId: CLIP } });
    expect(res.status).toBe(413);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('binds live scope by default and canary scope when cohort_id present', async () => {
    mockRpc({ fn_submit_motion_blind_review: () => ({ data: [submitRowNoPeer()], error: null }) });
    await POST(req(excludeBody), { params: { clipId: CLIP } });
    expect(rpc.mock.calls[0][1].p_cohort_kind).toBe('live');
    expect(rpc.mock.calls[0][1].p_cohort_id).toBeNull();

    rpc.mockClear();
    mockRpc({ fn_submit_motion_blind_review: () => ({ data: [submitRowNoPeer()], error: null }) });
    await POST(req({ ...excludeBody, cohort_id: COHORT }), { params: { clipId: CLIP } });
    expect(rpc.mock.calls[0][1].p_cohort_kind).toBe('canary');
    expect(rpc.mock.calls[0][1].p_cohort_id).toBe(COHORT);
  });

  it('stores first submission and returns awaiting_peer without any peer data', async () => {
    mockRpc({ fn_submit_motion_blind_review: () => ({ data: [submitRowNoPeer()], error: null }) });
    const res = await POST(req(excludeBody), { params: { clipId: CLIP } });
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body).toEqual({ status: 'awaiting_peer' });
    // finalize 는 호출되지 않는다.
    expect(rpc.mock.calls.some((c) => c[0] === 'fn_finalize_motion_blind_consensus')).toBe(false);
  });

  it('on second submission computes v1 comparison and finalizes with both digests', async () => {
    mockRpc({
      fn_submit_motion_blind_review: () => ({ data: [submitRowWithPeer()], error: null }),
      fn_finalize_motion_blind_consensus: () => ({ data: null, error: null }),
    });
    const res = await POST(req(excludeBody), { params: { clipId: CLIP } });
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.status).toBe('agreed'); // exclude vs exclude
    const finalizeCall = rpc.mock.calls.find((c) => c[0] === 'fn_finalize_motion_blind_consensus');
    expect(finalizeCall?.[1].p_comparator_version).toBe('motion-blind-v1');
    // canonical pair order by submission id: OWN(a...) < PEER(b...).
    expect(finalizeCall?.[1].p_submission_a).toBe(OWN);
    expect(finalizeCall?.[1].p_submission_b).toBe(PEER);
    expect(finalizeCall?.[1].p_digest_a).toBe('d-own');
    expect(finalizeCall?.[1].p_digest_b).toBe('d-peer');
    // 상대 원문은 응답에 없다.
    expect(JSON.stringify(body)).not.toContain('peer-secret-note');
  });

  it('retries finalize once on stale digest after re-read', async () => {
    let finalizeCalls = 0;
    rpc.mockImplementation((fn: string) => {
      if (fn === 'fn_submit_motion_blind_review') return Promise.resolve({ data: [submitRowWithPeer()], error: null });
      if (fn === 'fn_finalize_motion_blind_consensus') {
        finalizeCalls += 1;
        if (finalizeCalls === 1) return Promise.resolve({ data: null, error: { code: 'PT409' } });
        return Promise.resolve({ data: null, error: null });
      }
      return Promise.resolve({ data: null, error: null });
    });
    const res = await POST(req(excludeBody), { params: { clipId: CLIP } });
    expect(res.status).toBe(200);
    expect((await res.json()).status).toBe('agreed');
    expect(finalizeCalls).toBe(2);
  });

  it('returns idempotent awaiting for a duplicate same request with no peer', async () => {
    mockRpc({
      fn_submit_motion_blind_review: () => ({ data: [{ ...submitRowNoPeer(), is_duplicate: true }], error: null }),
    });
    const res = await POST(req(excludeBody), { params: { clipId: CLIP } });
    expect(res.status).toBe(200);
    expect((await res.json()).status).toBe('awaiting_peer');
  });

  it('returns 409 already_submitted on a different duplicate', async () => {
    mockRpc({ fn_submit_motion_blind_review: () => ({ data: null, error: { code: 'PT410', message: 'already_submitted raw' } }) });
    const res = await POST(req(excludeBody), { params: { clipId: CLIP } });
    expect(res.status).toBe(409);
    const body = await res.json();
    expect(body.code).toBe('already_submitted');
    expect(JSON.stringify(body)).not.toContain('raw');
  });

  it('maps stale/expired lease (PT424) to 410', async () => {
    mockRpc({ fn_submit_motion_blind_review: () => ({ data: null, error: { code: 'PT424' } }) });
    const res = await POST(req(excludeBody), { params: { clipId: CLIP } });
    expect(res.status).toBe(410);
    expect((await res.json()).code).toBe('stale_lease');
  });

  it('never returns peer decision/gt/note on conflict', async () => {
    mockRpc({
      fn_submit_motion_blind_review: () => ({
        data: [submitRowWithPeer({ peer_decision: 'hold', peer_reason_code: 'ambiguous', peer_note: 'peer-secret-note' })],
        error: null,
      }),
      fn_finalize_motion_blind_consensus: () => ({ data: null, error: null }),
    });
    const res = await POST(req(excludeBody), { params: { clipId: CLIP } });
    const body = await res.json();
    expect(body.status).toBe('conflict'); // exclude vs hold
    expect(body.differing_fields).toEqual(['decision']);
    const json = JSON.stringify(body);
    expect(json).not.toContain('peer-secret-note');
    expect(json).not.toContain('hold');
  });
});
