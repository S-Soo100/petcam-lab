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
const NOW = '2026-07-21T16:30:00.123456+00:00';

function req(body?: unknown) {
  return new NextRequest(`https://label.tera-ai.uk/api/labeling-v3/${CLIP}/decision`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

const triageRow = {
  clip_id: CLIP,
  owner_decision: 'label',
  decided_by: 'product-owner',
  decided_at: NOW,
  decision_note: null,
  created_at: NOW,
  updated_at: '2026-07-21T16:31:00.222222+00:00',
};

describe('POST /api/labeling-v3/[clipId]/decision', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireOwner.mockResolvedValue({ ok: true, userId: 'product-owner' });
    rpc.mockResolvedValue({ data: triageRow, error: null });
  });

  it('owner 가 아니면 가드 응답을 그대로 반환한다', async () => {
    requireOwner.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: 'forbidden' }, { status: 403 }),
    });
    const res = await POST(req({ decision: 'label' }), { params: { clipId: CLIP } });
    expect(res.status).toBe(403);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('잘못된 UUID 는 RPC 없이 400', async () => {
    const res = await POST(req({ decision: 'label' }), { params: { clipId: 'nope' } });
    expect(res.status).toBe(400);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('잘못된 decision enum 은 RPC 없이 400', async () => {
    const res = await POST(req({ decision: 'quarantine' }), { params: { clipId: CLIP } });
    expect(res.status).toBe(400);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('note 가 (trim 후) 10~500 밖이면 400', async () => {
    for (const note of ['  짧아  ', 'x'.repeat(501)]) {
      rpc.mockClear();
      const res = await POST(req({ decision: 'skip', note }), { params: { clipId: CLIP } });
      expect(res.status).toBe(400);
      expect(rpc).not.toHaveBeenCalled();
    }
  });

  it('label 결정을 bearer actor 로 정확한 payload 로 호출한다', async () => {
    await POST(req({ decision: 'label', expected_updated_at: NOW }), { params: { clipId: CLIP } });
    expect(rpc).toHaveBeenCalledWith('fn_decide_motion_clip_labeling', {
      p_clip_id: CLIP,
      p_actor_id: 'product-owner',
      p_decision: 'label',
      p_expected_updated_at: NOW,
      p_note: null,
    });
  });

  it('body 의 actor_id 를 무시하고 bearer owner 를 쓴다', async () => {
    await POST(req({ decision: 'hold', actor_id: 'evil', p_actor_id: 'evil' }), {
      params: { clipId: CLIP },
    });
    expect(rpc.mock.calls[0][1].p_actor_id).toBe('product-owner');
  });

  it('note 를 trim 해서 전달한다', async () => {
    await POST(req({ decision: 'skip', note: '  빈 그릇이라 제외 처리  ' }), {
      params: { clipId: CLIP },
    });
    expect(rpc.mock.calls[0][1].p_note).toBe('빈 그릇이라 제외 처리');
  });

  it('expected_updated_at 없으면 null', async () => {
    await POST(req({ decision: 'reset' }), { params: { clipId: CLIP } });
    expect(rpc.mock.calls[0][1].p_expected_updated_at).toBeNull();
    expect(rpc.mock.calls[0][1].p_decision).toBe('reset');
  });

  it('성공 응답에 decided_by(owner uuid) 를 담지 않는다', async () => {
    const res = await POST(req({ decision: 'label' }), { params: { clipId: CLIP } });
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.state).toBe('label');
    expect(body.updated_at).toBe('2026-07-21T16:31:00.222222+00:00');
    expect(JSON.stringify(body)).not.toContain('decided_by');
  });

  it('stale(PT409) 를 409 stale_state 로 매핑한다', async () => {
    rpc.mockResolvedValue({ data: null, error: { code: 'PT409', message: 'stale_state' } });
    const res = await POST(req({ decision: 'hold', expected_updated_at: NOW }), {
      params: { clipId: CLIP },
    });
    expect(res.status).toBe(409);
    expect((await res.json()).code).toBe('stale_state');
  });

  it('세션 있는 clip skip(PT410) 을 409 labeling_started 로 매핑한다', async () => {
    rpc.mockResolvedValue({ data: null, error: { code: 'PT410', message: 'labeling_started' } });
    const res = await POST(req({ decision: 'skip' }), { params: { clipId: CLIP } });
    expect(res.status).toBe(409);
    expect((await res.json()).code).toBe('labeling_started');
  });

  it('알 수 없는 DB 오류는 원문 없이 502', async () => {
    rpc.mockResolvedValue({
      data: null,
      error: { code: '08006', message: 'fn_decide_motion_clip_labeling connection lost' },
    });
    const res = await POST(req({ decision: 'label' }), { params: { clipId: CLIP } });
    expect(res.status).toBe(502);
    expect(JSON.stringify(await res.json())).not.toContain('fn_decide_motion_clip_labeling');
  });
});
