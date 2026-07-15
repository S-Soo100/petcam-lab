import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { requireOwner, from, rpc } = vi.hoisted(() => ({
  requireOwner: vi.fn(),
  from: vi.fn(),
  rpc: vi.fn(),
}));

vi.mock('@/lib/labelingAccess', () => ({ requireOwner }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { from, rpc } }));

import { GET, PATCH } from './route';

const CLIP = '380d97fd-0000-4000-8000-000000000001';
const NEXT_CLIP = '380d97fd-0000-4000-8000-000000000002';

function chain(result: unknown) {
  const c: Record<string, unknown> = {};
  for (const m of ['select', 'is', 'eq', 'or', 'order', 'limit', 'neq', 'gte', 'lte']) {
    c[m] = vi.fn(() => c);
  }
  c.then = (resolve: (v: unknown) => unknown) => resolve(result);
  return c;
}

function detailRow() {
  return {
    clip_id: CLIP,
    suggested_route: 'quarantine',
    suggestion_reason: 'gate_static',
    suggestion_source: 'gate_activity_policy',
    policy_version: 'gate-v2',
    owner_decision: null,
    decided_at: null,
    decision_note: null,
    updated_at: '2026-07-15T00:00:00.000Z',
    evidence_snapshot: { checkpoint: '/secret/ckpt.pt', producer_host: 'mac-mini.local' },
    camera_clips: { camera_id: 'cam-1', started_at: '2026-07-14T18:00:00.000Z', duration_sec: 30 },
  };
}

function detailReq(query = '?state=pending') {
  return new NextRequest(`https://label.tera-ai.uk/api/labeling-triage/${CLIP}${query}`);
}

function patchReq(body: unknown) {
  return new NextRequest(`https://label.tera-ai.uk/api/labeling-triage/${CLIP}`, {
    method: 'PATCH',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
}

describe('GET /api/labeling-triage/[clipId]', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireOwner.mockResolvedValue({ ok: true, userId: 'owner-1' });
  });

  it('returns the owner guard response unchanged', async () => {
    requireOwner.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: 'forbidden' }, { status: 403 }),
    });
    const res = await GET(detailReq(), { params: { clipId: CLIP } });
    expect(res.status).toBe(403);
  });

  it('rejects a non-UUID clip id', async () => {
    const res = await GET(detailReq(), { params: { clipId: 'not-a-uuid' } });
    expect(res.status).toBe(400);
  });

  it('rejects an invalid state', async () => {
    const res = await GET(detailReq('?state=bogus'), { params: { clipId: CLIP } });
    expect(res.status).toBe(400);
  });

  it('returns 404 when the triage row is absent', async () => {
    from.mockReturnValueOnce(chain({ data: [], error: null }));
    const res = await GET(detailReq(), { params: { clipId: CLIP } });
    expect(res.status).toBe(404);
  });

  it('returns detail + next_clip_id without raw evidence', async () => {
    from
      .mockReturnValueOnce(chain({ data: [detailRow()], error: null }))
      .mockReturnValueOnce(chain({ data: [{ clip_id: NEXT_CLIP }], error: null }));
    const res = await GET(detailReq(), { params: { clipId: CLIP } });
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.item.suggestion_source).toBe('gate_activity_policy');
    expect(body.item.policy_version).toBe('gate-v2');
    expect(body.next_clip_id).toBe(NEXT_CLIP);
    expect(JSON.stringify(body)).not.toContain('evidence_snapshot');
    expect(JSON.stringify(body)).not.toContain('checkpoint');
  });

  it('returns a generic 502 on a Supabase error', async () => {
    from.mockReturnValueOnce(chain({ data: null, error: { message: 'boom clip_labeling_triage' } }));
    const res = await GET(detailReq(), { params: { clipId: CLIP } });
    expect(res.status).toBe(502);
    expect(JSON.stringify(await res.json())).not.toContain('clip_labeling_triage');
  });

  it('rejects an invalid date filter with 400', async () => {
    const res = await GET(detailReq('?state=pending&date_from=nope'), { params: { clipId: CLIP } });
    expect(res.status).toBe(400);
  });

  it('returns 409 state_changed when URL state != actual effective state', async () => {
    // owner label 로 결정된 row 를 pending 탭으로 요청 → 실제 상태는 labeled.
    from.mockReturnValueOnce(
      chain({ data: [{ ...detailRow(), owner_decision: 'label' }], error: null }),
    );
    const res = await GET(detailReq('?state=pending'), { params: { clipId: CLIP } });
    expect(res.status).toBe(409);
    const body = await res.json();
    expect(body.code).toBe('state_changed');
    expect(body.state).toBe('labeled');
  });
});

describe('PATCH /api/labeling-triage/[clipId]', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireOwner.mockResolvedValue({ ok: true, userId: 'owner-1' });
    rpc.mockResolvedValue({
      data: { ok: true, row: { clip_id: CLIP, suggested_route: 'quarantine', owner_decision: 'label', updated_at: '2026-07-15T01:00:00.000Z' } },
      error: null,
    });
  });

  it('returns the owner guard response unchanged', async () => {
    requireOwner.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: 'forbidden' }, { status: 403 }),
    });
    const res = await PATCH(patchReq({ decision: 'label', expected_updated_at: '2026-07-15T00:00:00Z' }), { params: { clipId: CLIP } });
    expect(res.status).toBe(403);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('rejects a non-UUID clip id', async () => {
    const res = await PATCH(patchReq({ decision: 'label', expected_updated_at: '2026-07-15T00:00:00Z' }), { params: { clipId: 'nope' } });
    expect(res.status).toBe(400);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('rejects an unknown decision', async () => {
    const res = await PATCH(patchReq({ decision: 'delete', expected_updated_at: '2026-07-15T00:00:00Z' }), { params: { clipId: CLIP } });
    expect(res.status).toBe(400);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('rejects a missing expected_updated_at', async () => {
    const res = await PATCH(patchReq({ decision: 'label' }), { params: { clipId: CLIP } });
    expect(res.status).toBe(400);
  });

  it('rejects a note over 500 chars', async () => {
    const res = await PATCH(
      patchReq({ decision: 'label', expected_updated_at: '2026-07-15T00:00:00Z', note: 'x'.repeat(501) }),
      { params: { clipId: CLIP } },
    );
    expect(res.status).toBe(400);
    expect(rpc).not.toHaveBeenCalled();
  });

  it.each(['label', 'skip', 'reset'])('accepts a %s decision', async (decision) => {
    const res = await PATCH(patchReq({ decision, expected_updated_at: '2026-07-15T00:00:00Z' }), { params: { clipId: CLIP } });
    expect(res.status).toBe(200);
    expect(rpc).toHaveBeenCalledWith('fn_decide_clip_labeling_triage', {
      p_clip_id: CLIP,
      p_decided_by: 'owner-1',
      p_decision: decision,
      p_expected_updated_at: '2026-07-15T00:00:00Z',
      p_note: null,
    });
    expect(JSON.stringify(await res.json())).not.toContain('evidence');
  });

  it('maps not_found to 404', async () => {
    rpc.mockResolvedValue({ data: { ok: false, code: 'not_found' }, error: null });
    const res = await PATCH(patchReq({ decision: 'label', expected_updated_at: '2026-07-15T00:00:00Z' }), { params: { clipId: CLIP } });
    expect(res.status).toBe(404);
  });

  it('maps stale_state to 409', async () => {
    rpc.mockResolvedValue({ data: { ok: false, code: 'stale_state' }, error: null });
    const res = await PATCH(patchReq({ decision: 'skip', expected_updated_at: '2026-07-15T00:00:00Z' }), { params: { clipId: CLIP } });
    expect(res.status).toBe(409);
  });

  it('maps labeling_started to 409', async () => {
    rpc.mockResolvedValue({ data: { ok: false, code: 'labeling_started' }, error: null });
    const res = await PATCH(patchReq({ decision: 'skip', expected_updated_at: '2026-07-15T00:00:00Z' }), { params: { clipId: CLIP } });
    expect(res.status).toBe(409);
  });

  it('maps a 22023 RPC error to 400', async () => {
    rpc.mockResolvedValue({ data: null, error: { code: '22023', message: 'invalid' } });
    const res = await PATCH(patchReq({ decision: 'label', expected_updated_at: '2026-07-15T00:00:00Z' }), { params: { clipId: CLIP } });
    expect(res.status).toBe(400);
  });

  it('maps an unexpected RPC error to a generic 502', async () => {
    rpc.mockResolvedValue({ data: null, error: { code: '08006', message: 'connection to clip_labeling_triage lost' } });
    const res = await PATCH(patchReq({ decision: 'label', expected_updated_at: '2026-07-15T00:00:00Z' }), { params: { clipId: CLIP } });
    expect(res.status).toBe(502);
    expect(JSON.stringify(await res.json())).not.toContain('clip_labeling_triage');
  });
});
