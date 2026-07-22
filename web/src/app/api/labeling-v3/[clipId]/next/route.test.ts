import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

// owner 전용 "현재 필터의 다음 미분류 영상" 조회(설계 §6). 현재 clip 의 started_at 을 서버에서
// 다시 읽고, 기존 큐 RPC 를 unreviewed·cursor=(현재 started_at, 현재 id)·limit=1 로 재사용한다.

const { requireProductionLabelingAccess, rpc, from } = vi.hoisted(() => ({
  requireProductionLabelingAccess: vi.fn(),
  rpc: vi.fn(),
  from: vi.fn(),
}));

vi.mock('@/lib/labelingAccess', () => ({ requireProductionLabelingAccess }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc, from } }));

import { GET } from './route';

const CLIP = '11111111-1111-4111-8111-111111111111';
const NEXT = 'a1111111-1111-4111-8111-111111111111';
const CAM = '22222222-2222-4222-8222-222222222222';
const TS = '2026-07-21T16:30:00.123456+09:00';

function req(qs = '') {
  return new NextRequest(`https://label.tera-ai.uk/api/labeling-v3/${CLIP}/next${qs}`);
}

// motion_clips 현재 clip 조회 chain 모킹. clip=null 이면 빈 결과, dbError 면 error 반환.
function stubClip(clip: { id: string; started_at: string } | null, dbError: unknown = null) {
  const limit = vi.fn().mockResolvedValue({ data: clip ? [clip] : [], error: dbError });
  const eq = vi.fn(() => ({ limit }));
  const select = vi.fn(() => ({ eq }));
  from.mockReturnValue({ select });
  return { select, eq, limit };
}

function callGET(qs = '', clipId = CLIP) {
  return GET(req(qs), { params: { clipId } });
}

describe('GET /api/labeling-v3/[clipId]/next', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireProductionLabelingAccess.mockResolvedValue({
      ok: true,
      userId: 'product-owner',
      isOwner: true,
    });
    stubClip({ id: CLIP, started_at: TS });
    rpc.mockResolvedValue({ data: [{ clip_id: NEXT }], error: null });
  });

  it('owner: 현재 started_at 을 1회 조회하고 unreviewed cursor RPC 로 다음 영상을 찾는다', async () => {
    const res = await callGET();
    const body = await res.json();
    expect(body).toEqual({ next_clip_id: NEXT });

    expect(from).toHaveBeenCalledTimes(1);
    expect(from).toHaveBeenCalledWith('motion_clips');

    const args = rpc.mock.calls[0][1];
    expect(args).toMatchObject({
      p_is_owner: true,
      p_reviewer_id: 'product-owner',
      p_state: 'unreviewed',
      p_cursor_started_at: TS,
      p_cursor_id: CLIP, // same timestamp tie-break 를 위해 현재 id 를 cursor 로 넘긴다
      p_limit: 1,
    });
  });

  it('camera/date/media 필터를 RPC 로 전달한다', async () => {
    await callGET(
      `?camera_id=${CAM}&date_from=2026-07-21T00:00:00%2B09:00&date_to=2026-07-22T00:00:00%2B09:00&media=ready`,
    );
    const args = rpc.mock.calls[0][1];
    expect(args.p_camera_ids).toEqual([CAM]);
    expect(args.p_date_from).toBe('2026-07-21T00:00:00+09:00');
    expect(args.p_date_to).toBe('2026-07-22T00:00:00+09:00');
    expect(args.p_media).toBe('ready');
  });

  it('RPC 결과 0행이면 next_clip_id null(완료)', async () => {
    rpc.mockResolvedValue({ data: [], error: null });
    const res = await callGET();
    expect(await res.json()).toEqual({ next_clip_id: null });
  });

  it('access 가드 실패 응답을 그대로 반환한다', async () => {
    requireProductionLabelingAccess.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: 'forbidden' }, { status: 403 }),
    });
    const res = await callGET();
    expect(res.status).toBe(403);
    expect(from).not.toHaveBeenCalled();
    expect(rpc).not.toHaveBeenCalled();
  });

  it('labeler 는 403, DB 접근 0', async () => {
    requireProductionLabelingAccess.mockResolvedValue({
      ok: true,
      userId: 'labeler-1',
      isOwner: false,
    });
    const res = await callGET();
    expect(res.status).toBe(403);
    expect(from).not.toHaveBeenCalled();
    expect(rpc).not.toHaveBeenCalled();
  });

  it('잘못된 clip UUID 는 RPC 없이 400', async () => {
    const res = await callGET('', 'not-a-uuid');
    expect(res.status).toBe(400);
    expect(from).not.toHaveBeenCalled();
    expect(rpc).not.toHaveBeenCalled();
  });

  it('잘못된 필터는 RPC 없이 400', async () => {
    const res = await callGET('?camera_id=bad');
    expect(res.status).toBe(400);
    expect(from).not.toHaveBeenCalled();
    expect(rpc).not.toHaveBeenCalled();
  });

  it('현재 clip 이 없으면 404(RPC 없음)', async () => {
    stubClip(null);
    const res = await callGET();
    expect(res.status).toBe(404);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('현재 clip 조회 DB 오류는 공개 502(원문 비노출)', async () => {
    stubClip(null, { code: '08006', message: 'motion_clips connection lost' });
    const res = await callGET();
    expect(res.status).toBe(502);
    expect(JSON.stringify(await res.json())).not.toContain('motion_clips');
  });

  it('RPC 오류 원문은 공개 502 로 감춘다', async () => {
    rpc.mockResolvedValue({ data: null, error: { code: '08006', message: 'motion_clips connection lost' } });
    const res = await callGET();
    expect(res.status).toBe(502);
    expect(JSON.stringify(await res.json())).not.toContain('motion_clips');
  });

  it('안정 RPC 오류코드(22023)는 400 으로 매핑', async () => {
    rpc.mockResolvedValue({ data: null, error: { code: '22023', message: 'invalid filter' } });
    const res = await callGET();
    expect(res.status).toBe(400);
  });
});
