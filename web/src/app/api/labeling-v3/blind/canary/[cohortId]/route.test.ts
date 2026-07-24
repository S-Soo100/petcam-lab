import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

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
  for (const m of ['select', 'eq', 'is', 'in', 'order', 'limit']) b[m] = () => b;
  b.then = (resolve: (v: unknown) => unknown) => Promise.resolve(result).then(resolve);
  return b;
}
function setTables(tables: Record<string, unknown>) {
  from.mockImplementation((t: string) => builder(tables[t] ?? { data: [], error: null }));
}

function req(cohortId = COHORT) {
  return new NextRequest(`https://label.tera-ai.uk/api/labeling-v3/blind/canary/${cohortId}`);
}

// owner 대시보드용 슬롯 snapshot(clip 8 × reviewer 2 = 16 slot). ua 8/8 제출, ub 7/8 제출.
// reviewer 정본은 이 slot snapshot 이며 현재 group member 가 아니다(review-fix P1-3).
function ownerSlots() {
  const rows: { reviewer_id: string; submitted_at: string | null; clip_id: string }[] = [];
  for (let i = 0; i < 8; i += 1) rows.push({ reviewer_id: 'ua', submitted_at: 't', clip_id: `c${i}` });
  for (let i = 0; i < 8; i += 1)
    rows.push({ reviewer_id: 'ub', submitted_at: i < 7 ? 't' : null, clip_id: `c${i}` });
  return { data: rows, error: null };
}

describe('GET /api/labeling-v3/blind/canary/[cohortId]', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireProductionLabelingAccess.mockResolvedValue({ ok: true, userId: 'labeler-1', isOwner: false });
    setTables({
      motion_blind_review_cohorts: {
        data: [{ id: COHORT, status: 'open', kind: 'canary', label: '검증', group_id: 'grp' }],
        error: null,
      },
      motion_clip_review_slots: {
        data: [{ submitted_at: null }, { submitted_at: '2026-07-22T00:00:00Z' }],
        error: null,
      },
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

  it('미승인 접근은 403', async () => {
    const { NextResponse } = await import('next/server');
    requireProductionLabelingAccess.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: 'forbidden' }, { status: 403 }),
    });
    expect((await GET(req(), { params: { cohortId: COHORT } })).status).toBe(403);
  });

  it('400 for a malformed cohort id', async () => {
    expect((await GET(req('nope'), { params: { cohortId: 'nope' } })).status).toBe(400);
  });

  it('라벨러: 닫힌 cohort 는 만료(410), 개별 답안은 노출하지 않는다', async () => {
    setTables({
      motion_blind_review_cohorts: {
        data: [{ id: COHORT, status: 'closed', kind: 'canary', label: '검증', group_id: 'grp' }],
        error: null,
      },
    });
    const res = await GET(req(), { params: { cohortId: COHORT } });
    expect(res.status).toBe(410);
    expect((await res.json()).code).toBe('cohort_closed');
    expect(rpc).not.toHaveBeenCalled();
  });

  it('라벨러: 자기 canary slot 만 반환, cohort scope 고정', async () => {
    const res = await GET(req(), { params: { cohortId: COHORT } });
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.role).toBe('labeler');
    expect(body.cohort_id).toBe(COHORT);
    expect(body.items).toHaveLength(1);
    expect(body.total_count).toBe(2);
    expect(body.submitted_count).toBe(1);
    const args = rpc.mock.calls[0][1];
    expect(args.p_cohort_kind).toBe('canary');
    expect(args.p_cohort_id).toBe(COHORT);
    expect(args.p_reviewer_id).toBe('labeler-1');
  });

  it('라벨러 응답은 r2_key/peer 필드를 절대 흘리지 않는다', async () => {
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

  it('Owner: reviewer 별 submitted/total + 집계, 개별 제출 body 없음', async () => {
    requireProductionLabelingAccess.mockResolvedValue({ ok: true, userId: 'owner', isOwner: true });
    setTables({
      motion_blind_review_cohorts: {
        data: [{ id: COHORT, status: 'open', kind: 'canary', label: '검증', group_id: 'grp' }],
        error: null,
      },
      labeler_applications: {
        data: [
          { user_id: 'ua', display_name: '라벨러 A' },
          { user_id: 'ub', display_name: '라벨러 B' },
        ],
        error: null,
      },
      motion_clip_review_slots: ownerSlots(),
      motion_clip_consensus: {
        data: [{ status: 'agreed' }, { status: 'conflict' }, { status: 'awaiting' }],
        error: null,
      },
    });
    const res = await GET(req(), { params: { cohortId: COHORT } });
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.role).toBe('owner');
    // review-fix P1-3: reviewer 별 submitted_count / total_count 가 정확하다.
    expect(body.reviewers).toEqual([
      { display_name: '라벨러 A', submitted_count: 8, total_count: 8 },
      { display_name: '라벨러 B', submitted_count: 7, total_count: 8 },
    ]);
    expect(body.clip_total).toBe(8);
    expect(body.counts).toEqual({ awaiting: 1, agreed: 1, conflict: 1, owner_resolved: 0 });
    expect(body.share_path).toBe(`/labeling/blind/canary/${COHORT}`);
    // Owner 도 개별 답안(제출 원문)·reviewer UUID 는 못 본다(display_name/count 만).
    const json = JSON.stringify(body);
    expect(json).not.toContain('initial_gt');
    expect(json).not.toContain('decision');
    expect(json).not.toContain('reviewer_id');
    // rpc(개인 큐)는 owner branch 에서 호출하지 않는다.
    expect(rpc).not.toHaveBeenCalled();
  });

  it('Owner: canary reviewer 는 현재 group member 가 아니라 slot snapshot 이다(멤버 교체 후에도)', async () => {
    requireProductionLabelingAccess.mockResolvedValue({ ok: true, userId: 'owner', isOwner: true });
    setTables({
      motion_blind_review_cohorts: {
        data: [{ id: COHORT, status: 'open', kind: 'canary', label: '검증', group_id: 'grp' }],
        error: null,
      },
      // 현재 그룹 멤버는 교체됨(uc/ud) — 원래 canary reviewer(ua/ub)가 아니다.
      motion_labeling_review_group_members: {
        data: [{ user_id: 'uc' }, { user_id: 'ud' }],
        error: null,
      },
      labeler_applications: {
        data: [
          { user_id: 'ua', display_name: '원래에이' },
          { user_id: 'ub', display_name: '원래비' },
          { user_id: 'uc', display_name: '새시' },
          { user_id: 'ud', display_name: '새디' },
        ],
        error: null,
      },
      motion_clip_review_slots: ownerSlots(), // ua/ub snapshot
      motion_clip_consensus: { data: [], error: null },
    });
    const body = await (await GET(req(), { params: { cohortId: COHORT } })).json();
    expect(body.reviewers.map((r: { display_name: string }) => r.display_name)).toEqual([
      '원래에이',
      '원래비',
    ]);
    const json = JSON.stringify(body);
    // 교체된 새 멤버(uc/ud)는 canary reviewer 판정에 쓰지 않는다.
    expect(json).not.toContain('새시');
    expect(json).not.toContain('새디');
    // 현재 group member 테이블을 canary reviewer 판정에 조회하지 않는다.
    const tables = from.mock.calls.map((c: unknown[]) => c[0]);
    expect(tables).not.toContain('motion_labeling_review_group_members');
  });

  it('Owner: 닫힌 cohort 도 현황판을 받는다(만료 아님)', async () => {
    requireProductionLabelingAccess.mockResolvedValue({ ok: true, userId: 'owner', isOwner: true });
    setTables({
      motion_blind_review_cohorts: {
        data: [{ id: COHORT, status: 'closed', kind: 'canary', label: '검증', group_id: 'grp' }],
        error: null,
      },
      motion_labeling_review_group_members: { data: [], error: null },
      motion_clip_review_slots: { data: [], error: null },
      motion_clip_consensus: { data: [], error: null },
    });
    const res = await GET(req(), { params: { cohortId: COHORT } });
    expect(res.status).toBe(200);
    expect((await res.json()).status).toBe('closed');
  });
});
