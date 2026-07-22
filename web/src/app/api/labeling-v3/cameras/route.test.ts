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

const CAM_A = '22222222-2222-4222-8222-222222222222';
const CAM_B = '33333333-3333-4333-8333-333333333333';

// 체이너블 supabase 쿼리 모킹: 모든 메서드가 자신을 반환하고 await 시 result 로 resolve.
function chain(result: { data: unknown; error: unknown }) {
  const obj: Record<string, unknown> = {};
  for (const m of ['select', 'eq', 'in', 'order', 'not', 'limit']) {
    obj[m] = vi.fn(() => obj);
  }
  (obj as { then: unknown }).then = (resolve: (v: unknown) => unknown) =>
    resolve(result);
  return obj;
}

function req() {
  return new NextRequest('https://label.tera-ai.uk/api/labeling-v3/cameras');
}

describe('GET /api/labeling-v3/cameras', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireProductionLabelingAccess.mockResolvedValue({
      ok: true,
      userId: 'product-owner',
      isOwner: true,
    });
  });

  it('access 가드 실패 응답을 그대로 반환한다', async () => {
    requireProductionLabelingAccess.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: 'forbidden' }, { status: 403 }),
    });
    const res = await GET(req());
    expect(res.status).toBe(403);
    expect(from).not.toHaveBeenCalled();
    expect(rpc).not.toHaveBeenCalled();
  });

  it('owner 는 production cameras 전체를 반환한다', async () => {
    from.mockReturnValue(
      chain({
        data: [
          { id: CAM_A, name: '2번 카메라' },
          { id: CAM_B, name: '3번 카메라' },
        ],
        error: null,
      }),
    );
    const res = await GET(req());
    expect(from).toHaveBeenCalledWith('cameras');
    const body = await res.json();
    expect(body.cameras).toEqual([
      { id: CAM_A, name: '2번 카메라' },
      { id: CAM_B, name: '3번 카메라' },
    ]);
  });

  it('labeler 는 본인의 실제 처리 가능 큐 카메라를 distinct RPC 로 조회한다', async () => {
    rpc.mockResolvedValue({
      data: [
        { camera_id: CAM_A, camera_name: '2번 카메라' },
        { camera_id: CAM_B, camera_name: null },
      ],
      error: null,
    });
    requireProductionLabelingAccess.mockResolvedValue({
      ok: true,
      userId: 'labeler-1',
      isOwner: false,
    });
    const res = await GET(req());
    expect(rpc).toHaveBeenCalledWith('fn_list_motion_clip_labeling_camera_options', {
      p_reviewer_id: 'labeler-1',
    });
    expect(from).not.toHaveBeenCalled();
    const body = await res.json();
    expect(body.cameras).toEqual([
      { id: CAM_A, name: '2번 카메라' },
      { id: CAM_B, name: CAM_B },
    ]);
  });

  it('labeler 에 label 큐 카메라가 없으면 빈 배열', async () => {
    rpc.mockResolvedValue({ data: [], error: null });
    requireProductionLabelingAccess.mockResolvedValue({
      ok: true,
      userId: 'labeler-1',
      isOwner: false,
    });
    const res = await GET(req());
    const body = await res.json();
    expect(body.cameras).toEqual([]);
    expect(from).not.toHaveBeenCalled();
  });

  it('labeler RPC 응답의 내부 필드는 공개 응답에 노출하지 않는다', async () => {
    rpc.mockResolvedValue({
      data: [{
        camera_id: CAM_A,
        camera_name: '2번 카메라',
        reviewed_by: 'labeler-1',
        r2_key: 'clips/secret.mp4',
      }],
      error: null,
    });
    requireProductionLabelingAccess.mockResolvedValue({
      ok: true,
      userId: 'labeler-1',
      isOwner: false,
    });

    const res = await GET(req());
    const json = JSON.stringify(await res.json());

    expect(json).not.toContain('reviewed_by');
    expect(json).not.toContain('r2_key');
    expect(json).not.toContain('labeler-1');
    expect(json).not.toContain('secret.mp4');
  });

  it('DB 오류는 원문 없이 502', async () => {
    from.mockReturnValue(
      chain({ data: null, error: { code: '08006', message: 'cameras table lost' } }),
    );
    const res = await GET(req());
    expect(res.status).toBe(502);
    expect(JSON.stringify(await res.json())).not.toContain('cameras table');
  });

  it('labeler RPC 오류도 원문 없이 502', async () => {
    rpc.mockResolvedValue({
      data: null,
      error: { code: '08006', message: 'reviewer labeler-1 queue query failed' },
    });
    requireProductionLabelingAccess.mockResolvedValue({
      ok: true,
      userId: 'labeler-1',
      isOwner: false,
    });

    const res = await GET(req());
    const json = JSON.stringify(await res.json());

    expect(res.status).toBe(502);
    expect(json).not.toContain('labeler-1');
    expect(json).not.toContain('queue query failed');
  });
});
