import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { requireOwner, rpc } = vi.hoisted(() => ({
  requireOwner: vi.fn(),
  rpc: vi.fn(),
}));

vi.mock('@/lib/labelingAccess', () => ({ requireOwner }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));

import { POST } from './route';

const CLIP = '11111111-1111-4111-8111-111111111111';

function req(body: unknown) {
  return new NextRequest(`https://label.tera-ai.uk/api/labeling-v3/${CLIP}/vlm-review`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
}

describe('POST /api/labeling-v3/[clipId]/vlm-review', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // review-fix P0-2 후속: motion v3 VLM 검수는 Owner 전용(requireOwner). 기본 actor 는 owner.
    requireOwner.mockResolvedValue({ ok: true, userId: 'product-owner' });
    rpc.mockResolvedValue({ data: { stage: 'completed', completion_reason: 'vlm_reviewed' }, error: null });
  });

  it('requireOwner 인증 실패(401)를 그대로 반환하고 RPC 0회', async () => {
    requireOwner.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: 'unauthorized' }, { status: 401 }),
    });
    const res = await POST(req({ verdict: 'correct', error_tags: [] }), { params: { clipId: CLIP } });
    expect(res.status).toBe(401);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('requireOwner DEV_USER_ID 누락(503)을 그대로 반환하고 RPC 0회', async () => {
    requireOwner.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: 'owner administration unavailable' }, { status: 503 }),
    });
    const res = await POST(req({ verdict: 'correct', error_tags: [] }), { params: { clipId: CLIP } });
    expect(res.status).toBe(503);
    expect(rpc).not.toHaveBeenCalled();
  });

  // review-fix P0-2 후속: 라벨러(비-owner)는 labelers/tutorial·RPC 조회 없이 403 으로 막힌다.
  it('라벨러(비-owner)는 requireOwner 가 403 으로 막고 RPC 0회', async () => {
    requireOwner.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: 'forbidden' }, { status: 403 }),
    });
    const res = await POST(req({ verdict: 'correct', error_tags: [] }), { params: { clipId: CLIP } });
    expect(res.status).toBe(403);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('잘못된 UUID 는 400', async () => {
    const res = await POST(req({ verdict: 'correct', error_tags: [] }), { params: { clipId: 'nope' } });
    expect(res.status).toBe(400);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('verdict 있으면 검증 후 reviewer=bearer 로 완료 호출한다', async () => {
    await POST(req({ verdict: 'correct', error_tags: [], note: '일치' }), { params: { clipId: CLIP } });
    expect(rpc).toHaveBeenCalledWith('fn_complete_motion_clip_vlm_review', {
      p_clip_id: CLIP,
      p_reviewer_id: 'product-owner',
      p_verdict: 'correct',
      p_error_tags: [],
      p_review_note: '일치',
    });
  });

  it('잘못된 verdict enum 은 RPC 없이 400', async () => {
    const res = await POST(req({ verdict: 'maybe', error_tags: [] }), { params: { clipId: CLIP } });
    expect(res.status).toBe(400);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('incorrect 인데 error_tags 비면 400', async () => {
    const res = await POST(req({ verdict: 'incorrect', error_tags: [] }), { params: { clipId: CLIP } });
    expect(res.status).toBe(400);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('verdict 없으면 no_prediction 완료(p_verdict=null)', async () => {
    rpc.mockResolvedValue({ data: { stage: 'completed', completion_reason: 'no_prediction' }, error: null });
    await POST(req({}), { params: { clipId: CLIP } });
    expect(rpc).toHaveBeenCalledWith('fn_complete_motion_clip_vlm_review', {
      p_clip_id: CLIP,
      p_reviewer_id: 'product-owner',
      p_verdict: null,
      p_error_tags: [],
      p_review_note: null,
    });
  });

  it('gt_locked 세션 없음(P0002)은 404', async () => {
    rpc.mockResolvedValue({ data: null, error: { code: 'P0002', message: 'gt_locked session not found' } });
    const res = await POST(req({ verdict: 'correct', error_tags: [] }), { params: { clipId: CLIP } });
    expect(res.status).toBe(404);
  });

  it('prediction 없는데 verdict 강요(RPC 22023)는 400', async () => {
    rpc.mockResolvedValue({ data: null, error: { code: '22023', message: 'verdict required when prediction exists' } });
    const res = await POST(req({ verdict: 'correct', error_tags: [] }), { params: { clipId: CLIP } });
    expect(res.status).toBe(400);
  });

  it('알 수 없는 DB 오류는 원문 없이 502', async () => {
    rpc.mockResolvedValue({ data: null, error: { code: '08006', message: 'sessions table lost' } });
    const res = await POST(req({ verdict: 'correct', error_tags: [] }), { params: { clipId: CLIP } });
    expect(res.status).toBe(502);
    expect(JSON.stringify(await res.json())).not.toContain('sessions table');
  });
});
