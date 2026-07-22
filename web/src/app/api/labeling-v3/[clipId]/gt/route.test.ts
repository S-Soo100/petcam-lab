import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { requireProductionLabelingAccess, from, rpc, validateGroundTruth } = vi.hoisted(() => ({
  requireProductionLabelingAccess: vi.fn(),
  from: vi.fn(),
  rpc: vi.fn(),
  validateGroundTruth: vi.fn(),
}));

vi.mock('@/lib/labelingAccess', () => ({ requireProductionLabelingAccess }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { from, rpc } }));
vi.mock('@/lib/labelingV2', async (orig) => ({
  ...(await orig<Record<string, unknown>>()),
  validateGroundTruth,
}));

import { POST } from './route';

const CLIP = '11111111-1111-4111-8111-111111111111';

const VALID_GT = {
  visibility: 'visible',
  primary_action: 'moving',
  observed_actions: [],
  segments: [],
  target: 'none',
  human_confidence: 'certain',
  context_tags: [],
  activity_intensity: null,
  highlight_recommendation: 'exclude',
  enrichment_object: 'none',
  interaction_types: [],
  note: null,
};

function chain(result: { data: unknown; error: unknown }) {
  const obj: Record<string, unknown> = {};
  for (const m of ['select', 'eq', 'in', 'order', 'not', 'limit']) obj[m] = vi.fn(() => obj);
  (obj as { then: unknown }).then = (resolve: (v: unknown) => unknown) => resolve(result);
  return obj;
}
function makeFrom(results: Record<string, { data: unknown; error: unknown }>) {
  return (table: string) => chain(results[table] ?? { data: [], error: null });
}

function req(body: unknown) {
  return new NextRequest(`https://label.tera-ai.uk/api/labeling-v3/${CLIP}/gt`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
}

const okSession = { stage: 'gt_locked', prediction_snapshot: null };

function baseTables(jobs: unknown[] = []) {
  return makeFrom({
    motion_clips: { data: [{ duration_sec: 30, r2_key: 'terra-clips/x.mp4' }], error: null },
    clip_vlm_jobs: { data: jobs, error: null },
  });
}

describe('POST /api/labeling-v3/[clipId]/gt', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireProductionLabelingAccess.mockResolvedValue({ ok: true, userId: 'product-owner', isOwner: true });
    from.mockImplementation(baseTables());
    rpc.mockResolvedValue({ data: okSession, error: null });
    validateGroundTruth.mockImplementation((v: unknown) => v);
  });

  it('access 가드 실패를 그대로 반환한다', async () => {
    requireProductionLabelingAccess.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: 'forbidden' }, { status: 403 }),
    });
    const res = await POST(req(VALID_GT), { params: { clipId: CLIP } });
    expect(res.status).toBe(403);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('잘못된 UUID 는 400', async () => {
    const res = await POST(req(VALID_GT), { params: { clipId: 'nope' } });
    expect(res.status).toBe(400);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('source clip 없으면 404', async () => {
    from.mockImplementation(makeFrom({ motion_clips: { data: [], error: null } }));
    const res = await POST(req(VALID_GT), { params: { clipId: CLIP } });
    expect(res.status).toBe(404);
  });

  it('owner 는 사전 label 결정 없이 media-ready clip 을 원자적으로 잠근다', async () => {
    await POST(req(VALID_GT), { params: { clipId: CLIP } });
    expect(rpc).toHaveBeenCalledWith(
      'fn_lock_motion_clip_gt',
      expect.objectContaining({ p_clip_id: CLIP, p_reviewer_id: 'product-owner', p_is_owner: true }),
    );
  });

  it('client 는 prediction/reviewer/stage/initial_gt 를 주입할 수 없다', async () => {
    validateGroundTruth.mockImplementation((v: Record<string, unknown>) => v);
    await POST(
      req({
        ...VALID_GT,
        prediction_snapshot: { action: 'evil' },
        reviewed_by: 'evil',
        stage: 'completed',
        initial_gt: { x: 1 },
      }),
      { params: { clipId: CLIP } },
    );
    const args = rpc.mock.calls[0][1];
    expect(args.p_reviewer_id).toBe('product-owner'); // bearer, not body
    expect(args.p_prediction_snapshot).toBeNull(); // 서버 선택(성공 job 없음)
    // p_gt 는 화이트리스트 12필드만 — 주입 키 제거.
    expect(args.p_gt).not.toHaveProperty('prediction_snapshot');
    expect(args.p_gt).not.toHaveProperty('reviewed_by');
    expect(args.p_gt).not.toHaveProperty('stage');
    expect(args.p_gt).not.toHaveProperty('initial_gt');
  });

  it('최신 succeeded clip_vlm_jobs.result 를 prediction 으로 고른다(failed 무시)', async () => {
    from.mockImplementation(
      baseTables([
        { id: 'a', status: 'failed_terminal', result: { pick: 'no' }, completed_at: '2026-07-21T05:00:00Z' },
        { id: 'b', status: 'succeeded', result: { pick: 'yes' }, completed_at: '2026-07-21T04:00:00Z' },
      ]),
    );
    rpc.mockResolvedValue({ data: { stage: 'gt_locked', prediction_snapshot: { pick: 'yes' } }, error: null });
    const res = await POST(req(VALID_GT), { params: { clipId: CLIP } });
    expect(rpc.mock.calls[0][1].p_prediction_snapshot).toEqual({ pick: 'yes' });
    const body = await res.json();
    expect(body.requires_vlm_review).toBe(true);
    expect(body.prediction).toEqual({ pick: 'yes' });
  });

  it('succeeded 없으면 prediction null(스냅샷 조작 없음) → no_prediction', async () => {
    const res = await POST(req(VALID_GT), { params: { clipId: CLIP } });
    expect(rpc.mock.calls[0][1].p_prediction_snapshot).toBeNull();
    const body = await res.json();
    expect(body.requires_vlm_review).toBe(false);
  });

  it('labeler 는 label 아닌 clip 잠금 거부(PT403→404 은닉)', async () => {
    requireProductionLabelingAccess.mockResolvedValue({ ok: true, userId: 'labeler-1', isOwner: false });
    rpc.mockResolvedValue({ data: null, error: { code: 'PT403', message: 'labeler_forbidden' } });
    const res = await POST(req(VALID_GT), { params: { clipId: CLIP } });
    expect(res.status).toBe(404);
  });

  it('이미 잠긴 GT 재잠금(PT423) 은 409', async () => {
    rpc.mockResolvedValue({ data: null, error: { code: 'PT423', message: 'gt_already_locked' } });
    const res = await POST(req(VALID_GT), { params: { clipId: CLIP } });
    expect(res.status).toBe(409);
  });

  it('hold/skip 결정 clip 의 GT 잠금(PT424) 은 409 이고 Postgres 원문을 노출하지 않는다', async () => {
    rpc.mockResolvedValue({
      data: null,
      error: { code: 'PT424', message: 'decision_blocks_labeling at public.fn_lock_motion_clip_gt line 55' },
    });
    const res = await POST(req(VALID_GT), { params: { clipId: CLIP } });
    expect(res.status).toBe(409);
    const body = await res.json();
    expect(body.code).toBe('decision_blocks_labeling');
    expect(JSON.stringify(body)).not.toContain('fn_lock_motion_clip_gt');
    expect(JSON.stringify(body)).not.toContain('line 55');
  });

  it('GT 검증 실패는 issues 와 함께 400', async () => {
    const { GroundTruthValidationError } = await import('@/lib/labelingV2');
    validateGroundTruth.mockImplementation(() => {
      throw new GroundTruthValidationError([{ field: 'visibility', code: 'x', message: '가시성 필요' }]);
    });
    const res = await POST(req(VALID_GT), { params: { clipId: CLIP } });
    expect(res.status).toBe(400);
    expect((await res.json()).issues).toHaveLength(1);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('behavior_labels/Evidence 등 금지 테이블을 절대 호출하지 않는다', async () => {
    await POST(req(VALID_GT), { params: { clipId: CLIP } });
    const tables = from.mock.calls.map(([t]) => t);
    expect(tables).not.toContain('behavior_labels');
    expect(tables).not.toContain('local_vlm_evidence_annotations');
    expect(tables).not.toContain('clip_python_evidence_runs');
    expect(tables).not.toContain('clip_activity_assessments');
  });
});
