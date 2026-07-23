import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { requireProductionLabelingAccess, from, rpc } = vi.hoisted(() => ({
  requireProductionLabelingAccess: vi.fn(),
  from: vi.fn(),
  rpc: vi.fn(),
}));
vi.mock('@/lib/labelingAccess', () => ({ requireProductionLabelingAccess }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { from, rpc } }));

import { GET } from './route';

const COHORT = '22222222-2222-4222-8222-222222222222';
const CLIP = '11111111-1111-4111-8111-111111111111';

function builder(result: unknown) {
  const b: Record<string, unknown> = {};
  for (const m of ['select', 'eq', 'is', 'order', 'limit']) b[m] = () => b;
  b.then = (resolve: (v: unknown) => unknown) => Promise.resolve(result).then(resolve);
  return b;
}
function setTables(tables: Record<string, unknown>) {
  from.mockImplementation((t: string) => builder(tables[t] ?? { data: [], error: null }));
}

function req(cohortId = COHORT) {
  return new NextRequest(`https://label.tera-ai.uk/api/labeling-v3/blind/canary/${cohortId}`);
}

describe('GET /api/labeling-v3/blind/canary/[cohortId]', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireProductionLabelingAccess.mockResolvedValue({ ok: true, userId: 'labeler-1', isOwner: false });
    setTables({
      motion_blind_review_cohorts: { data: [{ id: COHORT, status: 'open', kind: 'canary' }], error: null },
      motion_clip_review_slots: { data: [{ submitted_at: null }, { submitted_at: '2026-07-22T00:00:00Z' }], error: null },
    });
    rpc.mockResolvedValue({
      data: [
        {
          clip_id: CLIP,
          camera_id: 'cam',
          camera_name: '검증 카메라',
          started_at: 't',
          duration_sec: 30,
          media_ready: true,
          activity_day_kst: '2026-07-22',
          lease_expires_at: null,
        },
      ],
      error: null,
    });
  });

  it('403 for owner', async () => {
    requireProductionLabelingAccess.mockResolvedValue({ ok: true, userId: 'owner', isOwner: true });
    expect((await GET(req(), { params: { cohortId: COHORT } })).status).toBe(403);
  });

  it('400 for a malformed cohort id', async () => {
    expect((await GET(req('nope'), { params: { cohortId: 'nope' } })).status).toBe(400);
  });

  it('410 for a closed cohort (safe expired link)', async () => {
    setTables({ motion_blind_review_cohorts: { data: [{ id: COHORT, status: 'closed', kind: 'canary' }], error: null } });
    const res = await GET(req(), { params: { cohortId: COHORT } });
    expect(res.status).toBe(410);
    expect((await res.json()).code).toBe('cohort_closed');
    expect(rpc).not.toHaveBeenCalled();
  });

  it('returns the reviewer canary slots pinned to cohort scope + progress', async () => {
    const res = await GET(req(), { params: { cohortId: COHORT } });
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.cohort_id).toBe(COHORT);
    expect(body.items).toHaveLength(1);
    expect(body.total_count).toBe(2);
    expect(body.submitted_count).toBe(1);
    // canary scope is pinned into the RPC.
    const args = rpc.mock.calls[0][1];
    expect(args.p_cohort_kind).toBe('canary');
    expect(args.p_cohort_id).toBe(COHORT);
    expect(args.p_reviewer_id).toBe('labeler-1');
  });

  it('never leaks r2_key/peer fields', async () => {
    rpc.mockResolvedValue({
      data: [
        {
          clip_id: CLIP, camera_name: 'x', started_at: 't', duration_sec: 30, media_ready: true,
          activity_day_kst: '2026-07-22', lease_expires_at: null, r2_key: 'secret.mp4', peer_decision: 'label',
        },
      ],
      error: null,
    });
    const json = JSON.stringify(await (await GET(req(), { params: { cohortId: COHORT } })).json());
    expect(json).not.toContain('r2_key');
    expect(json).not.toContain('peer_');
  });
});
