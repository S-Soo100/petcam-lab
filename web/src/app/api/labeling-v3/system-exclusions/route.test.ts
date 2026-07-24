import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { requireOwner, rpc } = vi.hoisted(() => ({
  requireOwner: vi.fn(),
  rpc: vi.fn(),
}));

vi.mock('@/lib/labelingAccess', () => ({ requireOwner }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));

import { GET } from './route';

function row(i: number, overrides: Record<string, unknown> = {}) {
  return {
    clip_id: `1111111${i}-1111-4111-8111-111111111111`.slice(0, 36),
    camera_name: '2번 카메라',
    started_at: '2026-07-21T16:30:00.123456+00:00',
    duration_sec: 4,
    displayed_duration_sec: 4,
    state: 'quarantined',
    rule_version: 'short-device-error-v1',
    quarantined_at: '2026-07-21T16:31:00+00:00',
    delete_after: '2026-07-28T16:31:00+00:00',
    media_deleted_at: null,
    media_ready: true,
    cursor_detected_at: '2026-07-21T16:31:00.500000+00:00',
    cursor_id: 'aaaaaaaa-1111-4111-8111-111111111111',
    // RPC 계약상 없어야 하지만, 혹시 유출되면 잡히도록 raw 키를 섞어 넣어 매퍼 화이트리스트를 검증.
    r2_key: 'terra-clips/clips/leak.mp4',
    delete_lease_token: 'lease-should-not-leak',
    ...overrides,
  };
}

function req(cursor?: string) {
  const url = new URL('https://label.tera-ai.uk/api/labeling-v3/system-exclusions');
  if (cursor) url.searchParams.set('cursor', cursor);
  return new NextRequest(url);
}

describe('GET /api/labeling-v3/system-exclusions', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireOwner.mockResolvedValue({ ok: true, userId: 'product-owner' });
  });

  it('비-owner(403)를 그대로 반환하고 RPC 0회', async () => {
    requireOwner.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: 'forbidden' }, { status: 403 }),
    });
    const res = await GET(req());
    expect(res.status).toBe(403);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('잘못된 cursor 는 DB 접근 전에 400', async () => {
    const res = await GET(req('!!!not-base64!!!'));
    expect(res.status).toBe(400);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('owner: 공개 필드만 매핑하고 raw/커서 필드는 노출하지 않는다', async () => {
    rpc.mockResolvedValue({ data: [row(0)], error: null });
    const res = await GET(req());
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.items).toHaveLength(1);
    expect(body.has_more).toBe(false);
    expect(body.next_cursor).toBeNull();
    const s = JSON.stringify(body);
    for (const leak of ['terra-clips', 'lease-should-not-leak', 'cursor_detected_at', 'cursor_id']) {
      expect(s).not.toContain(leak);
    }
    expect(body.items[0]).toMatchObject({
      state: 'quarantined',
      rule_version: 'short-device-error-v1',
      displayed_duration_sec: 4,
      media_ready: true,
    });
  });

  it('PAGE_SIZE+1 개면 has_more=true + opaque next_cursor 발급(내부 필드 비노출)', async () => {
    const rows = Array.from({ length: 51 }, (_, i) => row(i % 10));
    rpc.mockResolvedValue({ data: rows, error: null });
    const res = await GET(req());
    const body = await res.json();
    expect(body.items).toHaveLength(50);
    expect(body.has_more).toBe(true);
    expect(typeof body.next_cursor).toBe('string');
    expect(body.next_cursor).not.toContain('cursor_id');
  });

  it('RPC 오류는 일반화된 502(원문 미노출)', async () => {
    rpc.mockResolvedValue({ data: null, error: { code: 'XX000', message: 'internal detail xyz' } });
    const res = await GET(req());
    expect(res.status).toBe(502);
    expect(JSON.stringify(await res.json())).not.toContain('xyz');
  });
});
