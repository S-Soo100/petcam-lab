import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

// verifyRouterReviewer: owner bypass → labeler 멤버십. (튜토리얼 production 게이트는 2026-09-07 퇴역.)
const { verifyBearer, from, state } = vi.hoisted(() => {
  const state = { labelers: { data: [{ user_id: 'labeler-1' }] as unknown[] | null, error: null as unknown } };
  const limit = () => Promise.resolve(state.labelers);
  return {
    verifyBearer: vi.fn(),
    from: vi.fn(() => ({ select: () => ({ eq: () => ({ limit }) }) })),
    state,
  };
});

vi.mock('@/lib/clipPerms', () => ({ verifyBearer }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { from } }));

import { verifyRouterReviewer } from './_helpers';

const req = () =>
  new NextRequest('https://label.tera-ai.uk/api/router-review/items', {
    headers: { authorization: 'Bearer t' },
  });

describe('verifyRouterReviewer 멤버십 게이트', () => {
  const OLD = process.env.DEV_USER_ID;
  beforeEach(() => {
    vi.clearAllMocks();
    process.env.DEV_USER_ID = 'owner-x';
    verifyBearer.mockResolvedValue({ ok: true, auth: { userId: 'labeler-1' } });
    state.labelers = { data: [{ user_id: 'labeler-1' }], error: null };
  });
  afterEach(() => {
    process.env.DEV_USER_ID = OLD;
  });

  it('owner 는 labelers 조회 없이 bypass', async () => {
    verifyBearer.mockResolvedValue({ ok: true, auth: { userId: 'owner-x' } });
    const res = await verifyRouterReviewer(req());
    expect(res.ok).toBe(true);
    expect(from).not.toHaveBeenCalled();
  });

  it('labelers 멤버는 통과(추가 게이트 없음)', async () => {
    const res = await verifyRouterReviewer(req());
    expect(res.ok).toBe(true);
    expect(from).toHaveBeenCalledTimes(1);
  });

  it('labelers 멤버 아니면 403 forbidden', async () => {
    state.labelers = { data: [], error: null };
    const res = await verifyRouterReviewer(req());
    expect(res.ok).toBe(false);
    if (res.ok) return;
    expect(res.response.status).toBe(403);
  });

  it('labelers 조회 오류는 내부 메시지 없는 502', async () => {
    state.labelers = { data: null, error: { message: 'secret internal detail' } };
    const res = await verifyRouterReviewer(req());
    expect(res.ok).toBe(false);
    if (res.ok) return;
    expect(res.response.status).toBe(502);
    const body = await res.response.json();
    expect(JSON.stringify(body)).not.toContain('secret internal detail');
  });
});
