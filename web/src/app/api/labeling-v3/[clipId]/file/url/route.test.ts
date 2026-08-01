import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { requireOwner, from, presignGet } = vi.hoisted(() => ({
  requireOwner: vi.fn(),
  from: vi.fn(),
  presignGet: vi.fn(),
}));

vi.mock('@/lib/labelingAccess', () => ({ requireOwner }));
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
  requireOwner.mockResolvedValue({ ok: true, userId: 'product-owner' });
  from.mockImplementation(makeFrom(results));
}

function req(qs = '') {
  return new NextRequest(`https://label.tera-ai.uk/api/labeling-v3/${CLIP}/file/url${qs}`);
}

describe('GET /api/labeling-v3/[clipId]/file/url', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    presignGet.mockResolvedValue('https://r2.example/signed');
  });

  it('requireOwner 인증 실패(401)를 그대로 반환하고 DB·서명 0', async () => {
    requireOwner.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: 'unauthorized' }, { status: 401 }),
    });
    const res = await GET(req(), { params: { clipId: CLIP } });
    expect(res.status).toBe(401);
    expect(from).not.toHaveBeenCalled();
    expect(presignGet).not.toHaveBeenCalled();
  });

  it('requireOwner DEV_USER_ID 누락(503)을 그대로 반환하고 DB·서명 0', async () => {
    requireOwner.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: 'owner administration unavailable' }, { status: 503 }),
    });
    const res = await GET(req(), { params: { clipId: CLIP } });
    expect(res.status).toBe(503);
    expect(from).not.toHaveBeenCalled();
    expect(presignGet).not.toHaveBeenCalled();
  });

  it('잘못된 UUID 는 400', async () => {
    requireOwner.mockResolvedValue({ ok: true, userId: 'product-owner' });
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

  it('download=1은 attachment filename으로 별도 서명한다', async () => {
    ownerAccess({
      motion_clips: { data: [clipRow('terra-clips/clips/x.mp4')], error: null },
      motion_clip_labeling_triage: { data: [], error: null },
      motion_clip_labeling_sessions: { data: [], error: null },
    });
    const res = await GET(req('?download=1'), { params: { clipId: CLIP } });
    expect(presignGet).toHaveBeenCalledWith('terra-clips/clips/x.mp4', 3600, {
      downloadFilename: `petcam-${CLIP}.mp4`,
    });
    expect(await res.json()).toMatchObject({ filename: `petcam-${CLIP}.mp4` });
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

  // review-fix P0-2 후속: motion v3 미디어 URL 도 Owner 전용(requireOwner). 라벨러(비-owner)는
  // labelers/tutorial·clip DB 조회·서명 없이 403 으로 막힌다(우회 재생 차단).
  it('라벨러(비-owner)는 requireOwner 가 403 으로 막고 DB query·서명 0회', async () => {
    requireOwner.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: 'forbidden' }, { status: 403 }),
    });
    from.mockImplementation(
      makeFrom({
        motion_clips: { data: [clipRow('terra-clips/clips/x.mp4')], error: null },
        motion_clip_labeling_triage: { data: [{ owner_decision: 'label' }], error: null },
        motion_clip_labeling_sessions: { data: [], error: null },
      }),
    );
    const res = await GET(req(), { params: { clipId: CLIP } });
    expect(res.status).toBe(403);
    expect(from).not.toHaveBeenCalled();
    expect(presignGet).not.toHaveBeenCalled();
  });

  // 짧은 영상 자동 제외로 원본이 삭제된 clip 은 인가돼도 서명하지 않는다(410 media_deleted).
  it('media_deleted 면 410 media_deleted 이고 signer 0회', async () => {
    ownerAccess({
      motion_clips: { data: [clipRow('terra-clips/clips/x.mp4')], error: null },
      motion_clip_labeling_triage: { data: [], error: null },
      motion_clip_labeling_sessions: { data: [], error: null },
      motion_clip_system_exclusions: { data: [{ state: 'media_deleted' }], error: null },
    });
    const res = await GET(req(), { params: { clipId: CLIP } });
    expect(res.status).toBe(410);
    expect((await res.json()).code).toBe('media_deleted');
    expect(presignGet).not.toHaveBeenCalled();
  });
});
