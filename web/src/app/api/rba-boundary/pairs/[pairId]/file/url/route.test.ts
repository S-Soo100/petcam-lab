import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { requireLabelingAccess, rpc, presignGet } = vi.hoisted(() => ({
  requireLabelingAccess: vi.fn(),
  rpc: vi.fn(),
  presignGet: vi.fn(),
}));
vi.mock('@/lib/labelingAccess', () => ({ requireLabelingAccess }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));
vi.mock('@/lib/r2', () => ({ presignGet, SIGNED_URL_TTL_SEC: 3600 }));

import { GET } from './route';

const PAIR = '11111111-1111-4111-8111-111111111111';
function req(side = 'left') {
  return new NextRequest(`https://label.tera-ai.uk/api/rba-boundary/pairs/${PAIR}/file/url?side=${side}`);
}

describe('GET boundary pair media', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireLabelingAccess.mockResolvedValue({ ok: true, userId: 'peer-id', isOwner: false });
    rpc.mockResolvedValue({ data: [{ r2_key: 'private/key.mp4' }], error: null });
    presignGet.mockResolvedValue('https://signed.example/video');
  });

  it('활성 멤버+assignment RPC 뒤 URL만 반환하고 raw key는 숨긴다', async () => {
    const res = await GET(req(), { params: { pairId: PAIR } });
    const body = await res.json();
    expect(res.status).toBe(200);
    expect(presignGet).toHaveBeenCalledWith('private/key.mp4', 3600);
    expect(body.url).toContain('signed.example');
    expect(JSON.stringify(body)).not.toContain('private/key.mp4');
  });

  it('잘못된 side와 권한 회수 사용자를 signer 전에 막는다', async () => {
    expect((await GET(req('middle'), { params: { pairId: PAIR } })).status).toBe(400);
    requireLabelingAccess.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: 'forbidden' }, { status: 403 }),
    });
    expect((await GET(req(), { params: { pairId: PAIR } })).status).toBe(403);
    expect(presignGet).not.toHaveBeenCalled();
  });
});
