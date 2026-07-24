import { afterAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

const { requireProductionLabelingAccess, rpc } = vi.hoisted(() => ({
  requireProductionLabelingAccess: vi.fn(),
  rpc: vi.fn(),
}));
vi.mock('@/lib/labelingAccess', () => ({ requireProductionLabelingAccess }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));

import { GET } from './route';

const CAM_A = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const CAM_B = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
const CLIP = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const PREV_ENV = process.env.DEV_USER_ID;

function req(query = '') {
  return new NextRequest(`https://label.tera-ai.uk/api/labeling-v3/library${query}`);
}

function libraryRow(extra: Record<string, unknown> = {}) {
  return {
    clip_id: CLIP,
    camera_id: CAM_A,
    camera_name: '카메라',
    started_at: '2026-07-22T10:00:00Z',
    duration_sec: 30,
    label_state: 'awaiting',
    label_source: 'blind_consensus',
    final_decision: null,
    final_gt: null,
    ...extra,
  };
}

describe('GET /api/labeling-v3/library', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    process.env.DEV_USER_ID = 'owner-uuid';
    requireProductionLabelingAccess.mockResolvedValue({ ok: true, userId: 'labeler-1', isOwner: false });
    rpc.mockResolvedValue({ data: [libraryRow()], error: null });
  });
  afterAll(() => {
    process.env.DEV_USER_ID = PREV_ENV;
  });

  it('owner 와 라벨러 모두 허용', async () => {
    requireProductionLabelingAccess.mockResolvedValue({ ok: true, userId: 'owner', isOwner: true });
    expect((await GET(req())).status).toBe(200);
    requireProductionLabelingAccess.mockResolvedValue({ ok: true, userId: 'labeler-1', isOwner: false });
    expect((await GET(req())).status).toBe(200);
  });

  it('미승인은 requireProductionLabelingAccess 응답으로 차단', async () => {
    const { NextResponse } = await import('next/server');
    requireProductionLabelingAccess.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: 'forbidden' }, { status: 403 }),
    });
    expect((await GET(req())).status).toBe(403);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('모든 카메라 id 를 받고 그룹 필터를 붙이지 않는다', async () => {
    await GET(req(`?camera_id=${CAM_A}&camera_id=${CAM_B}`));
    const args = rpc.mock.calls[0][1];
    expect(args.p_camera_ids).toEqual([CAM_A, CAM_B]);
    expect(args).not.toHaveProperty('p_group_id');
  });

  it('잘못된 필터/커서는 400 code=invalid_request', async () => {
    const res = await GET(req('?label_state=nope'));
    expect(res.status).toBe(400);
    expect((await res.json()).code).toBe('invalid_request');
    expect((await GET(req('?cursor=!!broken!!')).then((r) => r.status))).toBe(400);
  });

  it('DEV_USER_ID 누락 시 503', async () => {
    delete process.env.DEV_USER_ID;
    expect((await GET(req())).status).toBe(503);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('next_cursor 는 마지막 raw started_at/clip_id 를 담는다', async () => {
    rpc.mockResolvedValue({
      data: [
        libraryRow({ clip_id: CLIP, started_at: '2026-07-22T10:00:00Z' }),
        libraryRow({ clip_id: CAM_B, started_at: '2026-07-22T09:00:00Z' }),
      ],
      error: null,
    });
    const res = await GET(req('?limit=1'));
    const body = await res.json();
    expect(body.items).toHaveLength(1);
    expect(body.has_more).toBe(true);
    expect(typeof body.next_cursor).toBe('string');
    // p_limit 은 limit+1 로 요청한다.
    expect(rpc.mock.calls[0][1].p_limit).toBe(2);
  });

  it('금지 필드 전체 목록이 주입돼도 응답 mapper 가 전부 버린다', async () => {
    rpc.mockResolvedValue({
      data: [
        libraryRow({
          r2_key: 'secret.mp4',
          reviewer_id: 'uuid',
          peer_decision: 'hold',
          digest: 'x',
          lease_token: 'tok',
          prediction_snapshot: {},
          evidence_snapshot: {},
          rank_features: {},
        }),
      ],
      error: null,
    });
    const json = JSON.stringify(await (await GET(req())).json());
    for (const forbidden of [
      'r2_key',
      'reviewer_id',
      'peer_',
      'digest',
      'lease_token',
      'prediction_snapshot',
      'evidence_snapshot',
      'rank_features',
    ]) {
      expect(json).not.toContain(forbidden);
    }
  });
});
