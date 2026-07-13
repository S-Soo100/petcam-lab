import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

// 레거시 /api/label 이 다시 무인증 쓰기로 열리지 않도록 owner-only 게이트를 고정한다.
const { verifyBearer, isOwnerId, insert, from } = vi.hoisted(() => {
  const insert = vi.fn(() => Promise.resolve({ error: null }));
  return {
    verifyBearer: vi.fn(),
    isOwnerId: vi.fn(),
    insert,
    from: vi.fn(() => ({ insert })),
  };
});

vi.mock('@/lib/clipPerms', () => ({ verifyBearer, isOwnerId }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { from } }));
vi.mock('next/cache', () => ({ revalidatePath: vi.fn() }));

import { POST } from './route';

function post(body: unknown) {
  return POST(
    new NextRequest('https://label.tera-ai.uk/api/label', {
      method: 'POST',
      headers: { 'content-type': 'application/json', authorization: 'Bearer t' },
      body: JSON.stringify(body),
    }),
  );
}

describe('POST /api/label (owner-only 잠금)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    verifyBearer.mockResolvedValue({ ok: true, auth: { userId: 'owner-1' } });
    isOwnerId.mockReturnValue(true);
    from.mockReturnValue({ insert });
    insert.mockResolvedValue({ error: null });
  });

  it('미인증은 401 이고 쓰기가 없다', async () => {
    verifyBearer.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: 'unauthorized' }, { status: 401 }),
    });
    const res = await post({ clip_id: 'c1', action: 'moving' });
    expect(res.status).toBe(401);
    expect(from).not.toHaveBeenCalled();
  });

  it('비-owner 는 403 이고 쓰기가 없다', async () => {
    isOwnerId.mockReturnValue(false);
    const res = await post({ clip_id: 'c1', action: 'moving' });
    expect(res.status).toBe(403);
    expect(from).not.toHaveBeenCalled();
  });

  it('owner + 유효 action 은 201, created_by=본인·source=human', async () => {
    const res = await post({ clip_id: 'c1', action: 'moving', notes: '  x  ' });
    expect(res.status).toBe(201);
    expect(insert).toHaveBeenCalledWith(
      expect.objectContaining({
        clip_id: 'c1',
        action: 'moving',
        source: 'human',
        verified: true,
        created_by: 'owner-1',
        notes: 'x',
      }),
    );
  });

  it('owner + 잘못된 action 은 400 이고 쓰기가 없다', async () => {
    const res = await post({ clip_id: 'c1', action: 'bogus' });
    expect(res.status).toBe(400);
    expect(from).not.toHaveBeenCalled();
  });

  it('clip_id 누락은 400', async () => {
    const res = await post({ action: 'moving' });
    expect(res.status).toBe(400);
  });
});
