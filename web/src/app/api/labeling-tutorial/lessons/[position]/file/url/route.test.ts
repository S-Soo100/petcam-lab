import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

// 미디어 라우트는 요청 lesson 의 clip 만 서명한다(일반 clip UUID 입력 경로 없음, 설계 §12).
const { requireLabelingAccess, helpers, presignGet } = vi.hoisted(() => ({
  requireLabelingAccess: vi.fn(),
  helpers: {
    parsePosition: (raw: string) => {
      const n = Number(raw);
      return Number.isInteger(n) && n >= 1 && n <= 5 ? n : null;
    },
    loadActiveSetId: vi.fn(),
    loadLessonByPosition: vi.fn(),
    loadLessonClip: vi.fn(),
  },
  presignGet: vi.fn(),
}));

vi.mock('@/lib/labelingAccess', () => ({ requireLabelingAccess }));
vi.mock('@/lib/r2', () => ({ presignGet, SIGNED_URL_TTL_SEC: 3600 }));
vi.mock('../../../../_helpers', () => helpers);

import { GET } from './route';

function get(position = '1') {
  return GET(new NextRequest('https://label.tera-ai.uk/x'), { params: { position } });
}

describe('GET tutorial file url', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireLabelingAccess.mockResolvedValue({ ok: true, userId: 'u1', isOwner: false });
    helpers.loadActiveSetId.mockResolvedValue('set1');
    helpers.loadLessonByPosition.mockResolvedValue({ id: 'l1', clip_id: 'clip1' });
    helpers.loadLessonClip.mockResolvedValue({ id: 'clip1', r2_key: 'clips/x.mp4' });
    presignGet.mockResolvedValue('https://r2/signed');
  });

  it('범위 밖 position 은 404 (loadLesson 미조회)', async () => {
    const res = await get('9');
    expect(res.status).toBe(404);
    expect(helpers.loadLessonByPosition).not.toHaveBeenCalled();
  });

  it('active set 없으면 404', async () => {
    helpers.loadActiveSetId.mockResolvedValue(null);
    expect((await get()).status).toBe(404);
  });

  it('lesson 없으면 404', async () => {
    helpers.loadLessonByPosition.mockResolvedValue(null);
    expect((await get()).status).toBe(404);
  });

  it('lesson clip 의 r2_key 로만 서명 URL 반환', async () => {
    const res = await get();
    expect(res.status).toBe(200);
    expect(presignGet).toHaveBeenCalledWith('clips/x.mp4', 3600);
    expect(await res.json()).toEqual({ url: 'https://r2/signed', ttl_sec: 3600, type: 'r2' });
  });

  it('r2_key 없으면 410', async () => {
    helpers.loadLessonClip.mockResolvedValue({ id: 'clip1', r2_key: null });
    expect((await get()).status).toBe(410);
    expect(presignGet).not.toHaveBeenCalled();
  });
});
