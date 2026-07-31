import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { requireProductionLabelingAccess, from, select } = vi.hoisted(() => ({
  requireProductionLabelingAccess: vi.fn(),
  from: vi.fn(),
  select: vi.fn(),
}));
vi.mock('@/lib/labelingAccess', () => ({ requireProductionLabelingAccess }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { from } }));

import { GET } from './route';

const CLIP = '11111111-1111-4111-8111-111111111111';
const COHORT = '22222222-2222-4222-8222-222222222222';

// thenable 빌더 — .select/.eq/.is/.limit 어디서 await 해도 table 결과를 반환한다.
function builder(result: unknown) {
  const b: Record<string, unknown> = {};
  b.select = (columns: string) => {
    select(columns);
    return b;
  };
  for (const m of ['eq', 'is', 'order', 'limit']) b[m] = () => b;
  b.then = (resolve: (v: unknown) => unknown) => Promise.resolve(result).then(resolve);
  return b;
}
function setTables(tables: Record<string, unknown>) {
  from.mockImplementation((t: string) => builder(tables[t] ?? { data: [], error: null }));
}

function req(qs = '') {
  return new NextRequest(`https://label.tera-ai.uk/api/labeling-v3/blind/${CLIP}${qs}`);
}

const clipRow = {
  id: CLIP,
  started_at: '2026-07-22T05:00:00.123456+09:00',
  duration_sec: 30,
  r2_key: 'terra-clips/secret.mp4',
  cameras: { name: '2번 카메라' },
};

describe('GET /api/labeling-v3/blind/[clipId]', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireProductionLabelingAccess.mockResolvedValue({ ok: true, userId: 'labeler-1', isOwner: false });
    setTables({
      motion_clip_review_slots: {
        data: [
          {
            reviewer_id: 'labeler-1',
            group_id: 'group-1',
            activity_day_kst: '2026-08-01',
            submitted_at: null,
            cohort_kind: 'live',
            cohort_id: null,
            comparator_version: 'motion-blind-live-v2-highlight-soft',
          },
          {
            reviewer_id: 'labeler-2',
            group_id: 'group-1',
            activity_day_kst: '2026-08-01',
            submitted_at: null,
            cohort_kind: 'live',
            cohort_id: null,
            comparator_version: 'motion-blind-live-v2-highlight-soft',
          },
        ],
        error: null,
      },
      motion_clips: { data: [clipRow], error: null },
    });
  });

  it('401 passthrough, 403 for owner', async () => {
    requireProductionLabelingAccess.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: 'unauthorized' }, { status: 401 }),
    });
    expect((await GET(req(), { params: { clipId: CLIP } })).status).toBe(401);
    requireProductionLabelingAccess.mockResolvedValue({ ok: true, userId: 'owner', isOwner: true });
    expect((await GET(req(), { params: { clipId: CLIP } })).status).toBe(403);
  });

  it('400 for a malformed clip id', async () => {
    const res = await GET(req(), { params: { clipId: 'not-a-uuid' } });
    expect(res.status).toBe(400);
  });

  it('404 not_assigned when the caller has no slot', async () => {
    setTables({ motion_clip_review_slots: { data: [], error: null }, motion_clips: { data: [clipRow], error: null } });
    const res = await GET(req(), { params: { clipId: CLIP } });
    expect(res.status).toBe(404);
    expect((await res.json()).code).toBe('not_assigned');
  });

  it('returns allowlisted detail without r2_key/peer/consensus', async () => {
    const res = await GET(req(), { params: { clipId: CLIP } });
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.clip.id).toBe(CLIP);
    expect(body.clip.own_submitted).toBe(false);
    expect(body.clip.comparator_version).toBe('motion-blind-live-v2-highlight-soft');
    expect(select).toHaveBeenCalledWith(
      'reviewer_id, group_id, activity_day_kst, submitted_at, cohort_kind, cohort_id, comparator_version',
    );
    const json = JSON.stringify(body);
    expect(json).not.toContain('r2_key');
    expect(json).not.toContain('secret.mp4');
    expect(json).not.toContain('lease_token');
    expect(json).not.toContain('peer');
  });

  it('maps a DB error to 502 without raw text', async () => {
    setTables({
      motion_clip_review_slots: { data: null, error: { message: 'motion_clip_review_slots boom' } },
    });
    const res = await GET(req(), { params: { clipId: CLIP } });
    expect(res.status).toBe(502);
    expect(JSON.stringify(await res.json())).not.toContain('boom');
  });

  it('canary scope requires an open cohort', async () => {
    setTables({
      motion_blind_review_cohorts: { data: [{ id: COHORT, status: 'closed', kind: 'canary' }], error: null },
    });
    const res = await GET(req(`?cohort_id=${COHORT}`), { params: { clipId: CLIP } });
    expect(res.status).toBe(410);
    expect((await res.json()).code).toBe('cohort_closed');
  });

  it('rejects a malformed cohort_id with 400', async () => {
    const res = await GET(req('?cohort_id=nope'), { params: { clipId: CLIP } });
    expect(res.status).toBe(400);
  });
});
