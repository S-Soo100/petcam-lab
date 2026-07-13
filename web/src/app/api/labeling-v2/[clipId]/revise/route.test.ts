import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

// requireOwner·supabase(rpc/from) 를 mock 하고 validator 는 실물 사용.
const { requireOwner, from, rpc } = vi.hoisted(() => ({
  requireOwner: vi.fn(),
  from: vi.fn(),
  rpc: vi.fn(),
}));

vi.mock('@/lib/labelingAccess', () => ({ requireOwner }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { from, rpc } }));
vi.mock('../../_helpers', () => ({ mapLickTarget: () => null }));

import { POST } from './route';

const VALID_GT = {
  visibility: 'visible',
  primary_action: 'moving',
  observed_actions: ['moving'],
  segments: [{ action: 'moving', start_sec: 0, end_sec: 30 }],
  target: 'none',
  human_confidence: 'certain',
  context_tags: [],
  activity_intensity: null,
  highlight_recommendation: 'include',
  enrichment_object: 'none',
  interaction_types: [],
  note: null,
};
const VALID_REVIEW = { verdict: 'correct', error_tags: [], note: null };
const REASON = '기준 GT 대상 오기입 정정 — 감사용 사유';

function post(body: unknown) {
  return POST(
    new NextRequest('https://label.tera-ai.uk/api/labeling-v2/clip1/revise', {
      method: 'POST',
      headers: { 'content-type': 'application/json', authorization: 'Bearer t' },
      body: JSON.stringify(body),
    }),
    { params: { clipId: 'clip1' } },
  );
}

function durationRows() {
  // camera_clips duration_sec 조회 체인.
  return { select: () => ({ eq: () => ({ limit: () => Promise.resolve({ data: [{ duration_sec: 30 }] }) }) }) };
}

describe('POST labeling-v2 revise (owner correction)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireOwner.mockResolvedValue({ ok: true, userId: 'owner' });
    from.mockImplementation(() => durationRows());
    rpc.mockResolvedValue({ data: { id: 's1', current_gt: VALID_GT, vlm_verdict: 'correct', updated_at: '2026-07-13T00:00:00Z' }, error: null });
  });

  it('무인증이면 requireOwner 의 401 을 그대로 반환', async () => {
    requireOwner.mockResolvedValue({ ok: false, response: NextResponse.json({ detail: 'unauthorized' }, { status: 401 }) });
    expect((await post({ gt: VALID_GT, vlm_review: VALID_REVIEW, reason: REASON })).status).toBe(401);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('비owner 면 403', async () => {
    requireOwner.mockResolvedValue({ ok: false, response: NextResponse.json({ detail: 'forbidden' }, { status: 403 }) });
    expect((await post({ gt: VALID_GT, vlm_review: VALID_REVIEW, reason: REASON })).status).toBe(403);
  });

  it('사유가 10자 미만이면 400 (RPC 미호출)', async () => {
    const res = await post({ gt: VALID_GT, vlm_review: VALID_REVIEW, reason: '짧아' });
    expect(res.status).toBe(400);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('GT 의미 위반이면 400 + issues[] (RPC 미호출)', async () => {
    const res = await post({ gt: { ...VALID_GT, primary_action: 'drinking', target: 'tool' }, vlm_review: VALID_REVIEW, reason: REASON });
    expect(res.status).toBe(400);
    expect(Array.isArray((await res.json()).issues)).toBe(true);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('대상 세션이 없으면(RPC P0002) 404', async () => {
    rpc.mockResolvedValue({ data: null, error: { code: 'P0002', message: 'completed session not found' } });
    expect((await post({ gt: VALID_GT, vlm_review: VALID_REVIEW, reason: REASON })).status).toBe(404);
  });

  it('DB 오류는 내부 메시지 숨긴 502', async () => {
    rpc.mockResolvedValue({ data: null, error: { code: 'XX000', message: 'internal boom detail' } });
    const res = await post({ gt: VALID_GT, vlm_review: VALID_REVIEW, reason: REASON });
    expect(res.status).toBe(502);
    const json = await res.json();
    expect(JSON.stringify(json)).not.toContain('boom');
  });

  it('clip 조회 DB 오류면 내부 메시지 숨긴 502 (RPC 미호출)', async () => {
    from.mockImplementation(() => ({
      select: () => ({ eq: () => ({ limit: () => Promise.resolve({ data: null, error: { message: 'boom clip lookup' } }) }) }),
    }));
    const res = await post({ gt: VALID_GT, vlm_review: VALID_REVIEW, reason: REASON });
    expect(res.status).toBe(502);
    expect(JSON.stringify(await res.json())).not.toContain('boom');
    expect(rpc).not.toHaveBeenCalled();
  });

  it('clip 이 없으면 404 (RPC 미호출)', async () => {
    from.mockImplementation(() => ({
      select: () => ({ eq: () => ({ limit: () => Promise.resolve({ data: [], error: null }) }) }),
    }));
    expect((await post({ gt: VALID_GT, vlm_review: VALID_REVIEW, reason: REASON })).status).toBe(404);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('duration 이 무효(null)면 60초 fallback 없이 502 (RPC 미호출)', async () => {
    // 60초 fallback 을 쓰면 잘못된 duration 으로 segment 가 저장될 수 있으므로 끊는다.
    from.mockImplementation(() => ({
      select: () => ({ eq: () => ({ limit: () => Promise.resolve({ data: [{ duration_sec: null }], error: null }) }) }),
    }));
    expect((await post({ gt: VALID_GT, vlm_review: VALID_REVIEW, reason: REASON })).status).toBe(502);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('성공하면 session/revised_at 반환하고 revised_by 는 서버가 결정(owner)', async () => {
    const res = await post({ gt: VALID_GT, vlm_review: VALID_REVIEW, reason: REASON, revised_by: 'attacker', session_id: 'x' });
    expect(res.status).toBe(200);
    const json = await res.json();
    expect(json.session.id).toBe('s1');
    expect(json.revised_at).toBe('2026-07-13T00:00:00Z');
    // body 의 revised_by/session_id 를 신뢰하지 않고 bearer owner + URL clipId 로 호출.
    const args = rpc.mock.calls[0][1];
    expect(args.p_revised_by).toBe('owner');
    expect(args.p_clip_id).toBe('clip1');
  });
});
