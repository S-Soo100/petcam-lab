import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { verifyBearer, isOwnerId, labelerQuery } = vi.hoisted(() => ({
  verifyBearer: vi.fn(),
  isOwnerId: vi.fn(),
  labelerQuery: {
    select: vi.fn(),
    eq: vi.fn(),
    limit: vi.fn(),
  },
}));
labelerQuery.select.mockReturnValue(labelerQuery);
labelerQuery.eq.mockReturnValue(labelerQuery);

vi.mock('@/lib/clipPerms', () => ({
  verifyBearer,
  isOwnerId,
  isLabeler: vi.fn(),
}));

vi.mock('@/lib/supabase', () => ({
  supabaseAdmin: {
    from: vi.fn(() => labelerQuery),
  },
}));

import { requireLabelingAccess, requireOwner } from './labelingAccess';

const request = new NextRequest('https://label.tera-ai.uk/api/test');

describe('labeling access guards', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    process.env.DEV_USER_ID = 'owner-user';
    verifyBearer.mockResolvedValue({ ok: true, auth: { userId: 'user-1' } });
    isOwnerId.mockReturnValue(false);
    labelerQuery.select.mockReturnValue(labelerQuery);
    labelerQuery.eq.mockReturnValue(labelerQuery);
    labelerQuery.limit.mockResolvedValue({ data: [], error: null });
  });

  it('returns the authentication failure unchanged', async () => {
    verifyBearer.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: 'unauthorized' }, { status: 401 }),
    });

    const result = await requireLabelingAccess(request);

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.response.status).toBe(401);
  });

  it('allows the owner without querying labelers', async () => {
    isOwnerId.mockReturnValue(true);

    const result = await requireLabelingAccess(request);

    expect(result).toEqual({ ok: true, userId: 'user-1', isOwner: true });
    expect(labelerQuery.select).not.toHaveBeenCalled();
  });

  it('allows an actual labelers member', async () => {
    labelerQuery.limit.mockResolvedValue({ data: [{ user_id: 'user-1' }], error: null });

    const result = await requireLabelingAccess(request);

    expect(result).toEqual({ ok: true, userId: 'user-1', isOwner: false });
  });

  it('blocks an authenticated pending user', async () => {
    const result = await requireLabelingAccess(request);

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.response.status).toBe(403);
  });

  it('fails closed when labeler membership cannot be read', async () => {
    labelerQuery.limit.mockResolvedValue({
      data: null,
      error: new Error('database unavailable'),
    });

    const result = await requireLabelingAccess(request);

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.response.status).toBe(502);
  });

  it('allows only DEV_USER_ID through the owner guard', async () => {
    isOwnerId.mockReturnValueOnce(false).mockReturnValueOnce(true);

    const denied = await requireOwner(request);
    const allowed = await requireOwner(request);

    expect(denied.ok).toBe(false);
    if (!denied.ok) expect(denied.response.status).toBe(403);
    expect(allowed).toEqual({ ok: true, userId: 'user-1' });
  });
});
