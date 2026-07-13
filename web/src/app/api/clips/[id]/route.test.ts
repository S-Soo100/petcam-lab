import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

// GET 은 loadClipWithPerms(mock)만 탄다. DELETE 는 supabaseAdmin.auth.getUser +
// from('camera_clips').select().eq().single() + from('camera_clips').delete().eq() + r2.deleteObject 를 탄다.
const { loadClipWithPerms, getUser, selectSingle, deleteResult, deleteObject } = vi.hoisted(() => ({
  loadClipWithPerms: vi.fn(),
  getUser: vi.fn(),
  selectSingle: vi.fn(),
  deleteResult: vi.fn(),
  deleteObject: vi.fn(),
}));

vi.mock('@/lib/clipPerms', () => ({ loadClipWithPerms }));

vi.mock('@/lib/supabase', () => ({
  supabaseAdmin: {
    auth: { getUser },
    from: vi.fn(() => ({
      select: () => ({ eq: () => ({ single: () => selectSingle() }) }),
      delete: () => ({ eq: () => deleteResult() }),
    })),
  },
}));

vi.mock('@/lib/r2', () => ({ deleteObject }));
vi.mock('next/cache', () => ({ revalidatePath: vi.fn() }));

import { DELETE, GET } from './route';

describe('GET /api/clips/[id]', () => {
  beforeEach(() => {
    vi.clearAllMocks();
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

describe('DELETE /api/clips/[id] (owner-only, atomic)', () => {
  const OWNER = 'owner-user';
  const CLIP = {
    id: 'clip-1',
    user_id: OWNER,
    r2_key: 'clips/clip-1.mp4',
    thumbnail_r2_key: 'clips/clip-1.jpg',
  };

  function del(id = 'clip-1', token: string | null = 't') {
    const headers: Record<string, string> = {};
    if (token) headers.authorization = `Bearer ${token}`;
    return DELETE(
      new NextRequest(`https://label.tera-ai.uk/api/clips/${id}`, { method: 'DELETE', headers }),
      { params: { id } },
    );
  }

  beforeEach(() => {
    vi.clearAllMocks();
    process.env.DEV_USER_ID = OWNER;
    getUser.mockResolvedValue({ data: { user: { id: OWNER } }, error: null });
    selectSingle.mockResolvedValue({ data: CLIP, error: null });
    deleteResult.mockResolvedValue({ error: null });
  });

  it('revision 존재(append-only 0A000) → 409, R2 미삭제, DB 부분삭제 없음', async () => {
    // 단일 camera_clips DELETE 가 트리거로 거부 → 아무것도 안 지워짐. R2 도 건드리지 않는다.
    deleteResult.mockResolvedValue({ error: { code: '0A000', message: 'append-only internal detail' } });
    const res = await del();
    expect(res.status).toBe(409);
    expect(JSON.stringify(await res.json())).not.toContain('append-only internal detail');
    expect(deleteObject).not.toHaveBeenCalled();
  });

  it('튜토리얼 FK 제한(RESTRICT 23503) → 409, R2 미삭제', async () => {
    deleteResult.mockResolvedValue({ error: { code: '23503', message: 'fk violation internal detail' } });
    const res = await del();
    expect(res.status).toBe(409);
    expect(JSON.stringify(await res.json())).not.toContain('fk violation internal detail');
    expect(deleteObject).not.toHaveBeenCalled();
  });

  it('그 외 DB 오류 → 일반 오류(내부 메시지 은닉), R2 미삭제', async () => {
    deleteResult.mockResolvedValue({ error: { code: 'XX000', message: 'secret boom detail' } });
    const res = await del();
    expect(res.status).toBe(500);
    expect(JSON.stringify(await res.json())).not.toContain('boom');
    expect(deleteObject).not.toHaveBeenCalled();
  });

  it('정상 삭제 → DB 성공 후 R2 원본+썸네일 삭제', async () => {
    const res = await del();
    expect(res.status).toBe(200);
    expect(deleteObject).toHaveBeenCalledWith('clips/clip-1.mp4');
    expect(deleteObject).toHaveBeenCalledWith('clips/clip-1.jpg');
  });

  it('R2 삭제 실패해도 요청은 성공(best-effort, DB 는 이미 지워짐)', async () => {
    deleteObject.mockRejectedValueOnce(new Error('r2 down'));
    const res = await del();
    expect(res.status).toBe(200);
    expect((await res.json()).r2_errors?.length).toBeGreaterThan(0);
  });

  it('무인증 401 (DB delete·R2 미호출)', async () => {
    const res = await del('clip-1', null);
    expect(res.status).toBe(401);
    expect(deleteResult).not.toHaveBeenCalled();
    expect(deleteObject).not.toHaveBeenCalled();
  });

  it('본인 소유 아니면 403 (DB delete·R2 미호출)', async () => {
    selectSingle.mockResolvedValue({ data: { ...CLIP, user_id: 'someone-else' }, error: null });
    const res = await del();
    expect(res.status).toBe(403);
    expect(deleteResult).not.toHaveBeenCalled();
    expect(deleteObject).not.toHaveBeenCalled();
  });
});
