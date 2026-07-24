import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

const { requireProductionLabelingAccess, rpc } = vi.hoisted(() => ({
  requireProductionLabelingAccess: vi.fn(),
  rpc: vi.fn(),
}));
vi.mock('@/lib/labelingAccess', () => ({ requireProductionLabelingAccess }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));

import { GET } from './route';

const CAM = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const SUB = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const CLIP = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';

function req(query = '') {
  return new NextRequest(`https://label.tera-ai.uk/api/labeling-v3/blind/history${query}`);
}

function historyRow(extra: Record<string, unknown> = {}) {
  return {
    submission_id: SUB,
    clip_id: CLIP,
    camera_id: CAM,
    camera_name: '카메라',
    started_at: '2026-07-22T10:00:00Z',
    duration_sec: 30,
    media_ready: true,
    submitted_at: '2026-07-22T11:00:00Z',
    decision: 'label',
    reason_code: 'behavior_data',
    initial_gt: { behavior: 'moving' },
    note: '내 메모',
    cohort_kind: 'live',
    final_status: 'conflict',
    ...extra,
  };
}

describe('GET /api/labeling-v3/blind/history', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireProductionLabelingAccess.mockResolvedValue({ ok: true, userId: 'labeler-1', isOwner: false });
    rpc.mockResolvedValue({ data: [historyRow()], error: null });
  });

  it('owner 는 403 — 개인 기록 엔드포인트가 아니다', async () => {
    requireProductionLabelingAccess.mockResolvedValue({ ok: true, userId: 'owner', isOwner: true });
    const res = await GET(req());
    expect(res.status).toBe(403);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('reviewer id 는 항상 bearer 에서만 온다(query 주입 무시)', async () => {
    await GET(req('?reviewer_id=evil-uuid'));
    expect(rpc.mock.calls[0][1].p_reviewer_id).toBe('labeler-1');
  });

  it('검증된 필터 + limit+1 로 RPC 호출', async () => {
    await GET(req(`?decision=label&cohort_kind=live&limit=5&camera_id=${CAM}`));
    const args = rpc.mock.calls[0][1];
    expect(args.p_decision).toBe('label');
    expect(args.p_cohort_kind).toBe('live');
    expect(args.p_camera_ids).toEqual([CAM]);
    expect(args.p_limit).toBe(6);
  });

  it('잘못된 필터는 DB 접근 전에 400', async () => {
    const res = await GET(req('?decision=nope'));
    expect(res.status).toBe(400);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('본인 GT/note 는 노출, final_status 는 2단계, 상대 원문은 없음', async () => {
    rpc.mockResolvedValue({
      data: [historyRow({ peer_decision: 'hold', digest: 'zzz', reviewer_id: 'peer-uuid' })],
      error: null,
    });
    const res = await GET(req());
    const body = await res.json();
    expect(body.items[0].initial_gt).toEqual({ behavior: 'moving' });
    expect(body.items[0].note).toBe('내 메모');
    expect(body.items[0].final_status).toBe('in_review'); // conflict 를 숨김
    const json = JSON.stringify(body);
    expect(json).not.toContain('peer_decision');
    expect(json).not.toContain('digest');
    expect(json).not.toContain('peer-uuid');
  });
});
