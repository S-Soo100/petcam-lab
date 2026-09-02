import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { requireOwner, rpc, presignGet } = vi.hoisted(() => ({
  requireOwner: vi.fn(),
  rpc: vi.fn(),
  presignGet: vi.fn(),
}));

vi.mock('@/lib/labelingAccess', () => ({ requireOwner }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));
vi.mock('@/lib/r2', () => ({ presignGet, SIGNED_URL_TTL_SEC: 300 }));

import { GET } from './route';

const CLIP = '11111111-1111-4111-8111-111111111111';
const R2_KEY = 'private/quarantine/clip.mp4';

function request(download = false) {
  return new NextRequest(
    `https://label.tera-ai.uk/api/labeling-v3/owner-media-cleanup/${CLIP}/file/url${download ? '?download=1' : ''}`,
  );
}

describe('GET owner-media-cleanup file URL', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireOwner.mockResolvedValue({ ok: true, userId: 'owner-id' });
    rpc.mockResolvedValue({ data: [{ r2_key: R2_KEY }], error: null });
    presignGet.mockResolvedValue('https://signed.example/video');
  });

  it('비-owner는 DB와 R2에 접근하지 않는다', async () => {
    requireOwner.mockResolvedValue({
      ok: false,
      response: NextResponse.json({}, { status: 403 }),
    });

    const res = await GET(request(), { params: { clipId: CLIP } });

    expect(res.status).toBe(403);
    expect(rpc).not.toHaveBeenCalled();
    expect(presignGet).not.toHaveBeenCalled();
  });

  it('전용 RPC가 허용한 격리 영상만 서명하고 저장 키는 응답에서 숨긴다', async () => {
    const res = await GET(request(), { params: { clipId: CLIP } });
    const body = await res.json();

    expect(res.status).toBe(200);
    expect(rpc).toHaveBeenCalledWith('fn_get_rba_owner_media_cleanup_key_v1', {
      p_owner_id: 'owner-id',
      p_clip_id: CLIP,
    });
    expect(presignGet).toHaveBeenCalledWith(R2_KEY, 300, undefined);
    expect(body).toEqual({ url: 'https://signed.example/video', expires_in: 300 });
    expect(JSON.stringify(body)).not.toContain(R2_KEY);
  });

  it('전용 RPC가 거절한 영상은 서명하지 않는다', async () => {
    rpc.mockResolvedValue({ data: [], error: null });

    const res = await GET(request(), { params: { clipId: CLIP } });

    expect(res.status).toBe(404);
    expect(presignGet).not.toHaveBeenCalled();
  });

  it('다운로드도 같은 전용 권한 확인 뒤 파일명만 추가한다', async () => {
    const res = await GET(request(true), { params: { clipId: CLIP } });

    expect(res.status).toBe(200);
    expect(presignGet).toHaveBeenCalledWith(R2_KEY, 300, {
      downloadFilename: `petcam-cleanup-${CLIP}.mp4`,
    });
  });
});
