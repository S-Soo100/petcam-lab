import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { requireProductionLabelingAccess, from } = vi.hoisted(() => ({
  requireProductionLabelingAccess: vi.fn(),
  from: vi.fn(),
}));

vi.mock('@/lib/labelingAccess', () => ({ requireProductionLabelingAccess }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { from } }));

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
    requireProductionLabelingAccess.mockResolvedValue({ ok: true, userId: 'product-owner', isOwner: true });
  });

  it('access 가드 실패를 그대로 반환한다', async () => {
    requireProductionLabelingAccess.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: 'forbidden' }, { status: 403 }),
    });
    const res = await GET(req(), { params: { clipId: CLIP } });
    expect(res.status).toBe(403);
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

  it('labeler 는 label 아닌 clip(세션도 없음)에 404(존재 은닉)', async () => {
    requireProductionLabelingAccess.mockResolvedValue({ ok: true, userId: 'labeler-1', isOwner: false });
    from.mockImplementation(
      makeFrom({
        motion_clips: { data: [clipRow], error: null },
        motion_clip_labeling_triage: { data: [{ owner_decision: 'hold' }], error: null },
        motion_clip_labeling_sessions: { data: [], error: null },
      }),
    );
    const res = await GET(req(), { params: { clipId: CLIP } });
    expect(res.status).toBe(404);
  });

  it('labeler 는 label clip 을 본다', async () => {
    requireProductionLabelingAccess.mockResolvedValue({ ok: true, userId: 'labeler-1', isOwner: false });
    from.mockImplementation(
      makeFrom({
        motion_clips: { data: [clipRow], error: null },
        motion_clip_labeling_triage: { data: [{ owner_decision: 'label' }], error: null },
        motion_clip_labeling_sessions: { data: [], error: null },
      }),
    );
    const res = await GET(req(), { params: { clipId: CLIP } });
    expect(res.status).toBe(200);
  });

  it('labeler 는 자기 세션 있는 clip 을 hold 여도 본다(세션 보호)', async () => {
    requireProductionLabelingAccess.mockResolvedValue({ ok: true, userId: 'labeler-1', isOwner: false });
    from.mockImplementation(
      makeFrom({
        motion_clips: { data: [clipRow], error: null },
        motion_clip_labeling_triage: { data: [{ owner_decision: 'hold' }], error: null },
        motion_clip_labeling_sessions: {
          data: [
            {
              stage: 'gt_locked',
              initial_gt: { primary_action: 'moving' },
              current_gt: { primary_action: 'moving' },
              prediction_snapshot: null,
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
    expect(res.status).toBe(200);
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
