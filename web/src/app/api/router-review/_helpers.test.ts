import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

// verifyRouterReviewer: owner bypass → labeler 멤버십 → tutorial production 게이트.
const { verifyBearer, from, tutorialGateResponse, state } = vi.hoisted(() => {
  const state = { labelers: { data: [{ user_id: 'labeler-1' }] as unknown[] | null, error: null as unknown } };
  const limit = () => Promise.resolve(state.labelers);
  return {
    verifyBearer: vi.fn(),
    from: vi.fn(() => ({ select: () => ({ eq: () => ({ limit }) }) })),
    tutorialGateResponse: vi.fn(),
    state,
  };
});

vi.mock('@/lib/clipPerms', () => ({ verifyBearer }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { from } }));
vi.mock('@/lib/labelingTutorialGate', () => ({ tutorialGateResponse }));

import { verifyRouterReviewer } from './_helpers';

const req = () =>
  new NextRequest('https://label.tera-ai.uk/api/router-review/items', {
    headers: { authorization: 'Bearer t' },
  });

describe('verifyRouterReviewer tutorial 게이트', () => {
  const OLD = process.env.DEV_USER_ID;
  beforeEach(() => {
    vi.clearAllMocks();
    process.env.DEV_USER_ID = 'owner-x';
    verifyBearer.mockResolvedValue({ ok: true, auth: { userId: 'labeler-1' } });
    state.labelers = { data: [{ user_id: 'labeler-1' }], error: null };
    tutorialGateResponse.mockResolvedValue(null); // 완료
  });
  afterEach(() => {
    process.env.DEV_USER_ID = OLD;
  });

  it('owner 는 labelers·tutorial 게이트 없이 bypass', async () => {
    verifyBearer.mockResolvedValue({ ok: true, auth: { userId: 'owner-x' } });
    const res = await verifyRouterReviewer(req());
    expect(res.ok).toBe(true);
    expect(from).not.toHaveBeenCalled();
    expect(tutorialGateResponse).not.toHaveBeenCalled();
  });

  it('튜토리얼 완료 labeler 는 통과', async () => {
    const res = await verifyRouterReviewer(req());
    expect(res.ok).toBe(true);
    expect(tutorialGateResponse).toHaveBeenCalledWith('labeler-1');
  });

  it('튜토리얼 미완료 labeler 는 403 tutorial_required', async () => {
    tutorialGateResponse.mockResolvedValue(
      NextResponse.json({ detail: 'tutorial_required' }, { status: 403 }),
    );
    const res = await verifyRouterReviewer(req());
    expect(res.ok).toBe(false);
    if (res.ok) return;
    expect(res.response.status).toBe(403);
    expect((await res.response.json()).detail).toBe('tutorial_required');
  });

  it('labelers 멤버 아니면 403 forbidden (튜토리얼 게이트 미도달)', async () => {
    state.labelers = { data: [], error: null };
    const res = await verifyRouterReviewer(req());
    expect(res.ok).toBe(false);
    if (res.ok) return;
    expect(res.response.status).toBe(403);
    expect(tutorialGateResponse).not.toHaveBeenCalled();
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
