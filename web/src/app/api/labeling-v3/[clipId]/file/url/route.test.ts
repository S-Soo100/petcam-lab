import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { requireProductionLabelingAccess, from, presignGet } = vi.hoisted(() => ({
  requireProductionLabelingAccess: vi.fn(),
  from: vi.fn(),
  presignGet: vi.fn(),
}));

vi.mock('@/lib/labelingAccess', () => ({ requireProductionLabelingAccess }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { from } }));
vi.mock('@/lib/r2', () => ({ presignGet, SIGNED_URL_TTL_SEC: 3600 }));

import { GET } from './route';

const CLIP = '11111111-1111-4111-8111-111111111111';
const CAM = '22222222-2222-4222-8222-222222222222';

function chain(result: { data: unknown; error: unknown }) {
  const obj: Record<string, unknown> = {};
  for (const m of ['select', 'eq', 'in', 'order', 'not', 'limit']) obj[m] = vi.fn(() => obj);
  (obj as { then: unknown }).then = (resolve: (v: unknown) => unknown) => resolve(result);
  return obj;
}

function makeFrom(results: Record<string, { data: unknown; error: unknown }>) {
  return (table: string) => chain(results[table] ?? { data: [], error: null });
}

function clipRow(r2Key: string | null) {
  return {
    id: CLIP,
    camera_id: CAM,
    started_at: '2026-07-21T16:30:00Z',
    duration_sec: 30,
    r2_key: r2Key,
    cameras: { name: '2번 카메라' },
  };
}

function ownerAccess(results: Record<string, { data: unknown; error: unknown }>) {
  requireProductionLabelingAccess.mockResolvedValue({ ok: true, userId: 'product-owner', isOwner: true });
  from.mockImplementation(makeFrom(results));
}

function req() {
  return new NextRequest(`https://label.tera-ai.uk/api/labeling-v3/${CLIP}/file/url`);
}

describe('GET /api/labeling-v3/[clipId]/file/url', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    presignGet.mockResolvedValue('https://r2.example/signed');
  });

  it('access 가드 실패를 그대로 반환한다', async () => {
    requireProductionLabelingAccess.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: 'forbidden' }, { status: 403 }),
    });
    const res = await GET(req(), { params: { clipId: CLIP } });
    expect(res.status).toBe(403);
    expect(from).not.toHaveBeenCalled();
  });

  it('잘못된 UUID 는 400', async () => {
    requireProductionLabelingAccess.mockResolvedValue({ ok: true, userId: 'product-owner', isOwner: true });
    const res = await GET(req(), { params: { clipId: 'nope' } });
    expect(res.status).toBe(400);
  });

  it('owner 는 r2_key 를 서버가 다시 읽어 서명하고 {url, expires_in} 만 반환한다', async () => {
    ownerAccess({
      motion_clips: { data: [clipRow('terra-clips/clips/x.mp4')], error: null },
      motion_clip_labeling_triage: { data: [], error: null },
      motion_clip_labeling_sessions: { data: [], error: null },
    });
    const res = await GET(req(), { params: { clipId: CLIP } });
    expect(res.status).toBe(200);
    expect(presignGet).toHaveBeenCalledWith('terra-clips/clips/x.mp4', 3600);
    const body = await res.json();
    expect(body).toEqual({ url: 'https://r2.example/signed', expires_in: 3600 });
    // r2_key 원문을 응답에 담지 않는다.
    expect(JSON.stringify(body)).not.toContain('terra-clips');
  });

  it('source clip 없으면 404', async () => {
    ownerAccess({ motion_clips: { data: [], error: null } });
    const res = await GET(req(), { params: { clipId: CLIP } });
    expect(res.status).toBe(404);
    expect(presignGet).not.toHaveBeenCalled();
  });

  it('r2_key 없으면 410', async () => {
    ownerAccess({
      motion_clips: { data: [clipRow(null)], error: null },
      motion_clip_labeling_triage: { data: [], error: null },
      motion_clip_labeling_sessions: { data: [], error: null },
    });
    const res = await GET(req(), { params: { clipId: CLIP } });
    expect(res.status).toBe(410);
    expect(presignGet).not.toHaveBeenCalled();
  });

  it('서명 실패는 502(원문 없이)', async () => {
    ownerAccess({
      motion_clips: { data: [clipRow('terra-clips/clips/x.mp4')], error: null },
      motion_clip_labeling_triage: { data: [], error: null },
      motion_clip_labeling_sessions: { data: [], error: null },
    });
    presignGet.mockRejectedValue(new Error('R2 credential missing secret-xyz'));
    const res = await GET(req(), { params: { clipId: CLIP } });
    expect(res.status).toBe(502);
    expect(JSON.stringify(await res.json())).not.toContain('secret-xyz');
  });

  it('labeler 는 label clip 만 재생 URL 을 받는다(비-label 은 404)', async () => {
    requireProductionLabelingAccess.mockResolvedValue({ ok: true, userId: 'labeler-1', isOwner: false });
    from.mockImplementation(
      makeFrom({
        motion_clips: { data: [clipRow('terra-clips/clips/x.mp4')], error: null },
        motion_clip_labeling_triage: { data: [{ owner_decision: 'skip' }], error: null },
        motion_clip_labeling_sessions: { data: [], error: null },
      }),
    );
    const res = await GET(req(), { params: { clipId: CLIP } });
    expect(res.status).toBe(404);
    expect(presignGet).not.toHaveBeenCalled();
  });
});
