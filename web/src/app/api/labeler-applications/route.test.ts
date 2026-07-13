import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

const { isLabeler, getUser, applicationQuery, from } = vi.hoisted(() => {
  const applicationQuery = {
    select: vi.fn(),
    eq: vi.fn(),
    limit: vi.fn(),
    insert: vi.fn(),
    update: vi.fn(),
    single: vi.fn(),
  };
  return {
    isLabeler: vi.fn(),
    getUser: vi.fn(),
    applicationQuery,
    from: vi.fn(() => applicationQuery),
  };
});

vi.mock('@/lib/clipPerms', () => ({ isLabeler }));
vi.mock('@/lib/supabase', () => ({
  supabaseAdmin: { auth: { getUser }, from },
}));

import { POST } from './route';

function request(body: unknown, token = 'valid-token') {
  return new NextRequest('https://label.tera-ai.uk/api/labeler-applications', {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      ...(token ? { authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
  });
}

describe('POST /api/labeler-applications', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    applicationQuery.select.mockReturnValue(applicationQuery);
    applicationQuery.eq.mockReturnValue(applicationQuery);
    applicationQuery.insert.mockReturnValue(applicationQuery);
    applicationQuery.update.mockReturnValue(applicationQuery);
    applicationQuery.limit.mockResolvedValue({ data: [], error: null });
    applicationQuery.single.mockResolvedValue({
      data: { user_id: 'user-1', status: 'pending' },
      error: null,
    });
    getUser.mockResolvedValue({
      data: { user: { id: 'user-1', email: 'trusted@example.com' } },
      error: null,
    });
    isLabeler.mockResolvedValue(false);
  });

  it('requires authentication', async () => {
    const response = await POST(request({ display_name: '홍길동' }, ''));
    expect(response.status).toBe(401);
  });

  it('rejects a blank display name', async () => {
    const response = await POST(request({ display_name: '   ' }));
    expect(response.status).toBe(400);
  });

  it('does not let an approved labeler create another application', async () => {
    isLabeler.mockResolvedValue(true);
    const response = await POST(request({ display_name: '홍길동' }));
    expect(response.status).toBe(409);
  });

  it('uses the authenticated email instead of a client supplied email', async () => {
    const response = await POST(
      request({ display_name: '홍길동', email: 'attacker@example.com' }),
    );

    expect(response.status).toBe(201);
    expect(applicationQuery.insert).toHaveBeenCalledWith(
      expect.objectContaining({
        user_id: 'user-1',
        email: 'trusted@example.com',
        display_name: '홍길동',
        status: 'pending',
      }),
    );
  });
});
