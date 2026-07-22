import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { requireOwner, from, rpc, validateGroundTruth } = vi.hoisted(() => ({
  requireOwner: vi.fn(),
  from: vi.fn(),
  rpc: vi.fn(),
  validateGroundTruth: vi.fn(),
}));

vi.mock('@/lib/labelingAccess', () => ({ requireOwner }));
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
  return new NextRequest(`https://label.tera-ai.uk/api/labeling-v3/${CLIP}/revise`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
}

const REASON = '기준 GT 대상 오기입 정정';

describe('POST /api/labeling-v3/[clipId]/revise', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireOwner.mockResolvedValue({ ok: true, userId: 'product-owner' });
    from.mockImplementation(makeFrom({ motion_clips: { data: [{ duration_sec: 30 }], error: null } }));
    rpc.mockResolvedValue({ data: { stage: 'completed' }, error: null });
    validateGroundTruth.mockImplementation((v: unknown) => v);
  });

  it('owner 아니면 가드 응답 그대로', async () => {
    requireOwner.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: 'forbidden' }, { status: 403 }),
    });
    const res = await POST(req({ gt: VALID_GT, reason: REASON }), { params: { clipId: CLIP } });
    expect(res.status).toBe(403);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('잘못된 UUID 는 400', async () => {
    const res = await POST(req({ gt: VALID_GT, reason: REASON }), { params: { clipId: 'nope' } });
    expect(res.status).toBe(400);
  });

  it('reason 이 (trim 후) 10~500 밖이면 400', async () => {
    for (const reason of ['  짧음  ', 'x'.repeat(501)]) {
      rpc.mockClear();
      const res = await POST(req({ gt: VALID_GT, reason }), { params: { clipId: CLIP } });
      expect(res.status).toBe(400);
      expect(rpc).not.toHaveBeenCalled();
    }
  });

  it('owner 보정을 화이트리스트 GT + trim reason 으로 호출한다', async () => {
    await POST(
      req({ gt: { ...VALID_GT, stage: 'x', reviewed_by: 'evil' }, reason: `  ${REASON}  ` }),
      { params: { clipId: CLIP } },
    );
    expect(rpc).toHaveBeenCalledWith('fn_revise_motion_clip_gt', {
      p_clip_id: CLIP,
      p_actor_id: 'product-owner',
      p_new_gt: expect.not.objectContaining({ stage: 'x', reviewed_by: 'evil' }),
      p_reason: REASON,
    });
  });

  it('completed 세션 없음(P0002)은 404', async () => {
    rpc.mockResolvedValue({ data: null, error: { code: 'P0002', message: 'completed session not found' } });
    const res = await POST(req({ gt: VALID_GT, reason: REASON }), { params: { clipId: CLIP } });
    expect(res.status).toBe(404);
  });

  it('금지 테이블을 호출하지 않는다', async () => {
    await POST(req({ gt: VALID_GT, reason: REASON }), { params: { clipId: CLIP } });
    const tables = from.mock.calls.map(([t]) => t);
    expect(tables).not.toContain('behavior_labels');
    expect(tables).not.toContain('local_vlm_evidence_annotations');
  });

  it('알 수 없는 DB 오류는 원문 없이 502', async () => {
    rpc.mockResolvedValue({ data: null, error: { code: '08006', message: 'revisions table lost' } });
    const res = await POST(req({ gt: VALID_GT, reason: REASON }), { params: { clipId: CLIP } });
    expect(res.status).toBe(502);
    expect(JSON.stringify(await res.json())).not.toContain('revisions table');
  });
});
