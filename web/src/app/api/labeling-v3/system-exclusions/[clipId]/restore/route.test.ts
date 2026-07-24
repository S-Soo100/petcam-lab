import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { requireOwner, rpc } = vi.hoisted(() => ({
  requireOwner: vi.fn(),
  rpc: vi.fn(),
}));

vi.mock('@/lib/labelingAccess', () => ({ requireOwner }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));

import { POST } from './route';

const CLIP = '11111111-1111-4111-8111-111111111111';

function req(body: unknown) {
  return new NextRequest(
    `https://label.tera-ai.uk/api/labeling-v3/system-exclusions/${CLIP}/restore`,
    { method: 'POST', body: typeof body === 'string' ? body : JSON.stringify(body) },
  );
}

const REASON = '정상 행동 영상으로 확인되어 복구';

describe('POST /api/labeling-v3/system-exclusions/[clipId]/restore', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireOwner.mockResolvedValue({ ok: true, userId: 'product-owner' });
    rpc.mockResolvedValue({ data: 'restored', error: null });
  });

  it('비-owner(403)를 그대로 반환하고 RPC 0회', async () => {
    requireOwner.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: 'forbidden' }, { status: 403 }),
    });
    const res = await POST(req({ reason: REASON }), { params: { clipId: CLIP } });
    expect(res.status).toBe(403);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('잘못된 UUID 는 400, RPC 0회', async () => {
    const res = await POST(req({ reason: REASON }), { params: { clipId: 'nope' } });
    expect(res.status).toBe(400);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('reason 이 10자 미만이면 400, RPC 0회', async () => {
    const res = await POST(req({ reason: '짧다' }), { params: { clipId: CLIP } });
    expect(res.status).toBe(400);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('reason 이 500자 초과면 400', async () => {
    const res = await POST(req({ reason: 'x'.repeat(501) }), { params: { clipId: CLIP } });
    expect(res.status).toBe(400);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('성공: bearer actor + reason 으로 RPC 호출하고 {ok:true}', async () => {
    const res = await POST(req({ reason: REASON }), { params: { clipId: CLIP } });
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ ok: true });
    expect(rpc).toHaveBeenCalledTimes(1);
    const [fn, args] = rpc.mock.calls[0];
    expect(fn).toBe('fn_restore_short_clip_exclusion');
    expect(args).toMatchObject({
      p_clip_id: CLIP,
      p_actor_id: 'product-owner',
      p_reason: REASON,
    });
    expect(typeof args.p_now).toBe('string');
  });

  it('media_deleted(PT428)는 409 media_deleted 로 매핑(원문 미노출)', async () => {
    rpc.mockResolvedValue({
      data: null,
      error: { code: 'PT428', message: 'media already deleted, cannot restore' },
    });
    const res = await POST(req({ reason: REASON }), { params: { clipId: CLIP } });
    expect(res.status).toBe(409);
    const body = await res.json();
    expect(body.code).toBe('media_deleted');
    expect(JSON.stringify(body)).not.toContain('cannot restore');
  });

  it('복구 불가 상태(PT409)는 409 로 매핑', async () => {
    rpc.mockResolvedValue({ data: null, error: { code: 'PT409', message: 'only quarantined' } });
    const res = await POST(req({ reason: REASON }), { params: { clipId: CLIP } });
    expect(res.status).toBe(409);
  });

  it('미지 오류는 일반화된 502', async () => {
    rpc.mockResolvedValue({ data: null, error: { code: 'XX000', message: 'boom secret' } });
    const res = await POST(req({ reason: REASON }), { params: { clipId: CLIP } });
    expect(res.status).toBe(502);
    expect(JSON.stringify(await res.json())).not.toContain('secret');
  });
});
