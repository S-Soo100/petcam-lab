import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { requireOwner, from, rpc } = vi.hoisted(() => ({
  requireOwner: vi.fn(),
  from: vi.fn(),
  rpc: vi.fn(),
}));

vi.mock('@/lib/labelingAccess', () => ({ requireOwner }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { from, rpc } }));

import { GET } from './route';

const CLIP = '11111111-1111-4111-8111-111111111111';
const CAM = '22222222-2222-4222-8222-222222222222';

function chain(result: { data: unknown; error: unknown }) {
  const obj: Record<string, unknown> = {};
  for (const m of ['select', 'eq', 'in', 'order', 'not', 'limit']) obj[m] = vi.fn(() => obj);
  (obj as { then: unknown }).then = (resolve: (v: unknown) => unknown) => resolve(result);
  return obj;
}

// 테이블명으로 결과를 분기하는 from 모킹.
function makeFrom(results: Record<string, { data: unknown; error: unknown }>) {
  return (table: string) => chain(results[table] ?? { data: [], error: null });
}

const clipRow = {
  id: CLIP,
  camera_id: CAM,
  started_at: '2026-07-21T16:30:00.123456+09:00',
  duration_sec: 30,
  r2_key: 'terra-clips/clips/x.mp4',
  cameras: { name: '2번 카메라' },
};

function req() {
  return new NextRequest(`https://label.tera-ai.uk/api/labeling-v3/${CLIP}`);
}

describe('GET /api/labeling-v3/[clipId]', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    delete process.env.LABELING_CANONICAL_GT_OWNER_READ_ENABLED;
    requireOwner.mockResolvedValue({ ok: true, userId: 'product-owner' });
  });

  it('canonical read flag off면 기존 응답 shape와 RPC 0회를 보존한다', async () => {
    from.mockImplementation(makeFrom({ motion_clips: { data: [clipRow], error: null }, motion_clip_labeling_triage: { data: [], error: null }, motion_clip_labeling_sessions: { data: [], error: null } }));
    const detail = await (await GET(req(), { params: { clipId: CLIP } })).json();
    expect(detail).not.toHaveProperty('canonical_gt');
    expect(rpc).not.toHaveBeenCalled();
  });

  it('canonical read flag on이면 canonical_gt를 병합한다', async () => {
    process.env.LABELING_CANONICAL_GT_OWNER_READ_ENABLED = 'true';
    from.mockImplementation(makeFrom({ motion_clips: { data: [clipRow], error: null }, motion_clip_labeling_triage: { data: [], error: null }, motion_clip_labeling_sessions: { data: [], error: null } }));
    rpc.mockResolvedValue({ data: { status: 'final', revision_id: CLIP, decision: 'hold', gt: null, source_type: 'blind_consensus', updated_at: '2026-08-04T00:00:00Z' }, error: null });
    const detail = await (await GET(req(), { params: { clipId: CLIP } })).json();
    expect(detail.canonical_gt).toMatchObject({ status: 'final', decision: 'hold', sourceLabel: '교차검수 합의' });
  });

  it('requireOwner 인증 실패(401)를 그대로 반환하고 DB 조회 0', async () => {
    requireOwner.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: 'unauthorized' }, { status: 401 }),
    });
    const res = await GET(req(), { params: { clipId: CLIP } });
    expect(res.status).toBe(401);
    expect(from).not.toHaveBeenCalled();
  });

  it('requireOwner DEV_USER_ID 누락(503)을 그대로 반환하고 DB 조회 0', async () => {
    requireOwner.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: 'owner administration unavailable' }, { status: 503 }),
    });
    const res = await GET(req(), { params: { clipId: CLIP } });
    expect(res.status).toBe(503);
    expect(from).not.toHaveBeenCalled();
  });

  it('잘못된 UUID 는 400', async () => {
    const res = await GET(req(), { params: { clipId: 'nope' } });
    expect(res.status).toBe(400);
    expect(from).not.toHaveBeenCalled();
  });

  it('owner 는 미분류 clip 을 blind(session 없음)로 본다 — prediction 속성 없음', async () => {
    from.mockImplementation(
      makeFrom({
        motion_clips: { data: [clipRow], error: null },
        motion_clip_labeling_triage: { data: [], error: null },
        motion_clip_labeling_sessions: { data: [], error: null },
      }),
    );
    const res = await GET(req(), { params: { clipId: CLIP } });
    expect(res.status).toBe(200);
    const detail = await res.json();
    expect(detail.id).toBe(CLIP);
    expect(detail.state).toBe('unreviewed');
    expect(detail.media_ready).toBe(true);
    expect(detail.session?.stage ?? 'draft').toBe('draft');
    expect(detail).not.toHaveProperty('prediction');
    expect(JSON.stringify(detail)).not.toContain('rank_features');
    expect(JSON.stringify(detail)).not.toContain('motion_summary');
    expect(JSON.stringify(detail)).not.toContain('r2_key');
  });

  it('GT 잠금 뒤에만 prediction 을 노출한다', async () => {
    from.mockImplementation(
      makeFrom({
        motion_clips: { data: [clipRow], error: null },
        motion_clip_labeling_triage: { data: [{ owner_decision: 'label' }], error: null },
        motion_clip_labeling_sessions: {
          data: [
            {
              stage: 'gt_locked',
              initial_gt: { primary_action: 'moving' },
              current_gt: { primary_action: 'moving' },
              prediction_snapshot: { action: 'drinking' },
              vlm_verdict: null,
              vlm_error_tags: [],
              vlm_review_note: null,
              completion_reason: null,
              gt_locked_at: '2026-07-21T16:31:00Z',
              completed_at: null,
            },
          ],
          error: null,
        },
      }),
    );
    const res = await GET(req(), { params: { clipId: CLIP } });
    const detail = await res.json();
    expect(detail.session.stage).toBe('gt_locked');
    expect(detail.prediction).toEqual({ action: 'drinking' });
  });

  it('source clip 없으면 404', async () => {
    from.mockImplementation(makeFrom({ motion_clips: { data: [], error: null } }));
    const res = await GET(req(), { params: { clipId: CLIP } });
    expect(res.status).toBe(404);
  });

  // review-fix P0-2 후속: motion v3 직접 상세는 Owner 전용(requireOwner). 라벨러(비-owner)는
  // labelers/tutorial·clip/triage/session DB 조회 없이 403 으로 막힌다. 승인 라벨러의 유일한 열람
  // 흐름은 /labeling/blind/** 뿐이다(우회로 기존 정답 열람 차단).
  it('라벨러(비-owner)는 requireOwner 가 403 으로 막고 DB query 0회', async () => {
    requireOwner.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: 'forbidden' }, { status: 403 }),
    });
    from.mockImplementation(
      makeFrom({
        motion_clips: { data: [clipRow], error: null },
        motion_clip_labeling_triage: { data: [{ owner_decision: 'label' }], error: null },
        motion_clip_labeling_sessions: { data: [], error: null },
      }),
    );
    const res = await GET(req(), { params: { clipId: CLIP } });
    expect(res.status).toBe(403);
    expect(from).not.toHaveBeenCalled();
  });

  it('DB 오류는 원문 없이 502', async () => {
    from.mockImplementation(
      makeFrom({ motion_clips: { data: null, error: { code: '08006', message: 'motion_clips lost' } } }),
    );
    const res = await GET(req(), { params: { clipId: CLIP } });
    expect(res.status).toBe(502);
    expect(JSON.stringify(await res.json())).not.toContain('motion_clips');
  });
});
