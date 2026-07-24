import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

const { requireProductionLabelingAccess, from, presignGet } = vi.hoisted(() => ({
  requireProductionLabelingAccess: vi.fn(),
  from: vi.fn(),
  presignGet: vi.fn(),
}));
vi.mock('@/lib/labelingAccess', () => ({ requireProductionLabelingAccess }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { from } }));
vi.mock('@/lib/r2', () => ({ presignGet, SIGNED_URL_TTL_SEC: 300 }));

import { GET } from './route';

const CLIP = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';

function builder(result: unknown) {
  const b: Record<string, unknown> = {};
  for (const m of ['select', 'eq', 'limit']) b[m] = () => b;
  b.then = (resolve: (v: unknown) => unknown) => Promise.resolve(result).then(resolve);
  return b;
}
function setClip(result: unknown) {
  from.mockImplementation(() => builder(result));
}
function req() {
  return new NextRequest(`https://label.tera-ai.uk/api/labeling-v3/library/${CLIP}/file/url`);
}

describe('GET /api/labeling-v3/library/[clipId]/file/url', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireProductionLabelingAccess.mockResolvedValue({ ok: true, userId: 'labeler-1', isOwner: false });
    setClip({ data: [{ r2_key: 'clips/x.mp4' }], error: null });
    presignGet.mockResolvedValue('https://signed.example/x.mp4');
  });

  it('인증 실패면 그 응답을 그대로 반환(DB·서명 접근 X)', async () => {
    const { NextResponse } = await import('next/server');
    requireProductionLabelingAccess.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: 'forbidden' }, { status: 403 }),
    });
    expect((await GET(req(), { params: { clipId: CLIP } })).status).toBe(403);
    expect(from).not.toHaveBeenCalled();
    expect(presignGet).not.toHaveBeenCalled();
  });

  it('잘못된 UUID 는 400', async () => {
    const res = await GET(
      new NextRequest('https://label.tera-ai.uk/api/labeling-v3/library/nope/file/url'),
      { params: { clipId: 'nope' } },
    );
    expect(res.status).toBe(400);
    expect(from).not.toHaveBeenCalled();
  });

  it('r2_key 없으면 410', async () => {
    setClip({ data: [{ r2_key: null }], error: null });
    expect((await GET(req(), { params: { clipId: CLIP } })).status).toBe(410);
    expect(presignGet).not.toHaveBeenCalled();
  });

  it('서명 실패는 502', async () => {
    presignGet.mockRejectedValue(new Error('boom'));
    expect((await GET(req(), { params: { clipId: CLIP } })).status).toBe(502);
  });

  it('성공 응답은 정확히 {url, expires_in} 이고 r2_key 는 없다', async () => {
    const res = await GET(req(), { params: { clipId: CLIP } });
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body).toEqual({ url: 'https://signed.example/x.mp4', expires_in: 300 });
    expect(JSON.stringify(body)).not.toContain('r2_key');
  });
});
