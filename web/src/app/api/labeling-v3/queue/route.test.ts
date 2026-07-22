import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { requireProductionLabelingAccess, rpc } = vi.hoisted(() => ({
  requireProductionLabelingAccess: vi.fn(),
  rpc: vi.fn(),
}));

vi.mock('@/lib/labelingAccess', () => ({ requireProductionLabelingAccess }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));

import { GET } from './route';

const CAM = '22222222-2222-4222-8222-222222222222';

function req(qs = '') {
  return new NextRequest(`https://label.tera-ai.uk/api/labeling-v3/queue${qs}`);
}

function rpcRow(overrides: Record<string, unknown> = {}) {
  return {
    clip_id: '11111111-1111-4111-8111-111111111111',
    camera_id: CAM,
    camera_name: '2번 카메라',
    started_at: '2026-07-21T16:30:00.123456+09:00',
    duration_sec: 30,
    media_ready: true,
    state: 'unreviewed',
    session_stage: null,
    state_updated_at: null,
    ...overrides,
  };
}

describe('GET /api/labeling-v3/queue', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireProductionLabelingAccess.mockResolvedValue({
      ok: true,
      userId: 'product-owner',
      isOwner: true,
    });
    rpc.mockResolvedValue({ data: [], error: null });
  });

  it('access 가드 실패 응답을 그대로 반환한다', async () => {
    requireProductionLabelingAccess.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: 'forbidden' }, { status: 403 }),
    });
    const res = await GET(req());
    expect(res.status).toBe(403);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('owner 를 owner_id 필터 없이 p_is_owner/p_reviewer_id 로 호출한다', async () => {
    await GET(req('?state=all'));
    expect(rpc).toHaveBeenCalledWith(
      'fn_list_motion_clip_labeling_queue',
      expect.objectContaining({ p_is_owner: true, p_reviewer_id: 'product-owner' }),
    );
    const args = rpc.mock.calls[0][1];
    expect(args).not.toHaveProperty('p_owner_id');
    // state=all → p_state null
    expect(args.p_state).toBeNull();
  });

  it('owner state 필터를 그대로 전달한다', async () => {
    for (const state of ['unreviewed', 'label', 'hold', 'skip']) {
      rpc.mockClear();
      await GET(req(`?state=${state}`));
      expect(rpc.mock.calls[0][1].p_state).toBe(state);
    }
  });

  it('잘못된 state 는 RPC 없이 400', async () => {
    const res = await GET(req('?state=quarantine'));
    expect(res.status).toBe(400);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('labeler 는 항상 label 큐(state 무시, p_is_owner=false)', async () => {
    requireProductionLabelingAccess.mockResolvedValue({
      ok: true,
      userId: 'labeler-1',
      isOwner: false,
    });
    await GET(req('?state=skip'));
    const args = rpc.mock.calls[0][1];
    expect(args.p_is_owner).toBe(false);
    expect(args.p_reviewer_id).toBe('labeler-1');
    expect(args.p_state).toBeNull();
  });

  it('잘못된 camera_id/date/media/limit/cursor 는 RPC 없이 400', async () => {
    for (const qs of [
      '?camera_id=not-a-uuid',
      '?date_from=2026-07-21', // offset 없는 RFC3339 아님
      '?date_to=nope',
      '?media=maybe',
      '?limit=0',
      '?limit=-3',
      '?limit=abc',
      '?cursor=%%%bad',
    ]) {
      rpc.mockClear();
      const res = await GET(req(qs));
      expect(res.status, qs).toBe(400);
      expect(rpc, qs).not.toHaveBeenCalled();
    }
  });

  it('유효 필터를 RPC 인자로 변환한다', async () => {
    await GET(
      req(
        `?camera_id=${CAM}&date_from=2026-07-21T00:00:00%2B09:00&date_to=2026-07-22T00:00:00%2B09:00&media=ready&limit=10`,
      ),
    );
    const args = rpc.mock.calls[0][1];
    expect(args.p_camera_ids).toEqual([CAM]);
    expect(args.p_date_from).toBe('2026-07-21T00:00:00+09:00');
    expect(args.p_date_to).toBe('2026-07-22T00:00:00+09:00');
    expect(args.p_media).toBe('ready');
    // limit+1 을 요청해 has_more 를 판정한다.
    expect(args.p_limit).toBe(11);
  });

  it('has_more 판정 + next_cursor 가 DB 마이크로초를 verbatim 보존한다', async () => {
    // limit 2 요청 → RPC 3건 반환 → has_more, 앞 2건만 노출, cursor 는 2번째 row 기준.
    rpc.mockResolvedValue({
      data: [
        rpcRow({ clip_id: 'a1111111-1111-4111-8111-111111111111', started_at: '2026-07-21T16:30:00.500000+09:00' }),
        rpcRow({ clip_id: 'b1111111-1111-4111-8111-111111111111', started_at: '2026-07-21T16:29:00.123456+09:00' }),
        rpcRow({ clip_id: 'c1111111-1111-4111-8111-111111111111', started_at: '2026-07-21T16:28:00.000000+09:00' }),
      ],
      error: null,
    });
    const res = await GET(req('?limit=2'));
    const body = await res.json();
    expect(body.items).toHaveLength(2);
    expect(body.has_more).toBe(true);
    // cursor 디코드해 마이크로초가 살아있는지 확인.
    const { decodeQueueCursor } = await import('@/lib/labelingQueueCursor');
    const pos = decodeQueueCursor(body.next_cursor);
    expect(pos?.startedAt).toBe('2026-07-21T16:29:00.123456+09:00');
    expect(pos?.id).toBe('b1111111-1111-4111-8111-111111111111');
  });

  it('공개 limit=100 은 DB 상한 안에서 99개 페이지의 has_more 를 판정한다', async () => {
    const rows = Array.from({ length: 100 }, (_, index) =>
      rpcRow({
        clip_id: `${String(index).padStart(8, '0')}-1111-4111-8111-111111111111`,
        started_at: `2026-07-21T16:${String(59 - Math.floor(index / 60)).padStart(2, '0')}:${String(59 - (index % 60)).padStart(2, '0')}.123456+09:00`,
      }),
    );
    rpc.mockResolvedValue({ data: rows, error: null });

    const res = await GET(req('?limit=100'));
    const body = await res.json();

    expect(rpc.mock.calls[0][1].p_limit).toBe(100);
    expect(body.items).toHaveLength(99);
    expect(body.has_more).toBe(true);
    expect(body.next_cursor).not.toBeNull();
  });

  it('마지막 페이지는 next_cursor null', async () => {
    rpc.mockResolvedValue({ data: [rpcRow()], error: null });
    const res = await GET(req('?limit=30'));
    const body = await res.json();
    expect(body.has_more).toBe(false);
    expect(body.next_cursor).toBeNull();
  });

  it('응답에 r2_key/owner/evidence/prediction 이 없다', async () => {
    rpc.mockResolvedValue({
      data: [rpcRow({ r2_key: 'terra-clips/secret.mp4', owner_id: 'oooo', evidence_snapshot: { x: 1 }, prediction_snapshot: { a: 1 } })],
      error: null,
    });
    const res = await GET(req());
    const json = JSON.stringify(await res.json());
    expect(json).not.toContain('r2_key');
    expect(json).not.toContain('owner_id');
    expect(json).not.toContain('evidence');
    expect(json).not.toContain('prediction');
  });

  it('알 수 없는 RPC 오류는 원문 없이 502', async () => {
    rpc.mockResolvedValue({ data: null, error: { code: '08006', message: 'motion_clips connection lost' } });
    const res = await GET(req());
    expect(res.status).toBe(502);
    expect(JSON.stringify(await res.json())).not.toContain('motion_clips');
  });

  it('안정 RPC 오류코드(22023)는 400 으로 매핑', async () => {
    rpc.mockResolvedValue({ data: null, error: { code: '22023', message: 'invalid state filter' } });
    const res = await GET(req());
    expect(res.status).toBe(400);
  });
});
