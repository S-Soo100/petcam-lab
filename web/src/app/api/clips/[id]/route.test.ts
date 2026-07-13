import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { loadClipWithPerms, verifyBearer, clipQuery } = vi.hoisted(() => ({
  loadClipWithPerms: vi.fn(),
  verifyBearer: vi.fn(),
  clipQuery: {
    select: vi.fn(),
    eq: vi.fn(),
    limit: vi.fn(),
  },
}));
clipQuery.select.mockReturnValue(clipQuery);
clipQuery.eq.mockReturnValue(clipQuery);
clipQuery.limit.mockResolvedValue({
  data: [{ id: 'clip-1', user_id: 'pending-user' }],
  error: null,
});

vi.mock('@/lib/clipPerms', () => ({
  loadClipWithPerms,
  verifyBearer,
}));

vi.mock('@/lib/supabase', () => ({
  supabaseAdmin: {
    from: vi.fn(() => clipQuery),
  },
}));

vi.mock('@/lib/r2', () => ({ deleteObject: vi.fn() }));

import { GET } from './route';

describe('GET /api/clips/[id]', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    clipQuery.select.mockReturnValue(clipQuery);
    clipQuery.eq.mockReturnValue(clipQuery);
    clipQuery.limit.mockResolvedValue({
      data: [{ id: 'clip-1', user_id: 'pending-user' }],
      error: null,
    });
    verifyBearer.mockResolvedValue({
      ok: true,
      auth: { userId: 'pending-user' },
    });
  });

  it('blocks a pending user through the shared labeling access gate', async () => {
    loadClipWithPerms.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: 'not found' }, { status: 404 }),
    });

    const response = await GET(
      new NextRequest('https://label.tera-ai.uk/api/clips/clip-1'),
      { params: { id: 'clip-1' } },
    );

    expect(response.status).toBe(404);
    expect(loadClipWithPerms).toHaveBeenCalledOnce();
  });

  it('returns the clip selected by the shared access helper', async () => {
    const clip = {
      id: 'clip-1',
      user_id: 'owner-user',
      r2_key: 'clips/clip-1.mp4',
      thumbnail_r2_key: null,
      file_path: null,
      thumbnail_path: null,
    };
    loadClipWithPerms.mockResolvedValue({
      ok: true,
      access: { userId: 'labeler-user', clip, isOwner: false },
    });

    const response = await GET(
      new NextRequest('https://label.tera-ai.uk/api/clips/clip-1'),
      { params: { id: 'clip-1' } },
    );

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual(clip);
  });
});
