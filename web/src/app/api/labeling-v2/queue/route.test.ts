import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

// access / queue collector / supabase 는 mock. cursor 계약은 실제 모듈로 round-trip 검증한다.
const { requireProductionLabelingAccess, collectQueuePage, from } = vi.hoisted(() => ({
  requireProductionLabelingAccess: vi.fn(),
  collectQueuePage: vi.fn(),
  from: vi.fn(),
}));

vi.mock('@/lib/labelingAccess', () => ({ requireProductionLabelingAccess }));
vi.mock('@/lib/labelingQueue', () => ({ collectQueuePage }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { from } }));

import { GET } from './route';
import { decodeQueueCursor, encodeQueueCursor } from '@/lib/labelingQueueCursor';

const UUID_A = '11111111-1111-4111-8111-111111111111';

// 모든 체이닝 메서드가 self 를 반환하고 await 하면 preset 결과로 resolve 되는 stub.
function chain(result: unknown) {
  const c: Record<string, unknown> = {};
  for (const m of ['select', 'is', 'eq', 'not', 'or', 'order', 'limit', 'in', 'gte', 'lte']) {
    c[m] = vi.fn(() => c);
  }
  c.then = (resolve: (v: unknown) => unknown) => resolve(result);
  return c;
}

function req(query = '') {
  return new NextRequest(`https://label.tera-ai.uk/api/labeling-v2/queue${query}`);
}

describe('GET /api/labeling-v2/queue', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireProductionLabelingAccess.mockResolvedValue({
      ok: true,
      userId: 'owner-1',
      isOwner: true,
    });
  });

  it('returns the access guard response unchanged', async () => {
    requireProductionLabelingAccess.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: 'tutorial_required' }, { status: 403 }),
    });
    const res = await GET(req());
    expect(res.status).toBe(403);
    expect(collectQueuePage).not.toHaveBeenCalled();
  });

  it('returns 400 invalid_cursor before DB access', async () => {
    const response = await GET(req('?cursor=bad!'));
    expect(response.status).toBe(400);
    expect(await response.json()).toEqual({
      detail: '페이지 위치가 올바르지 않아.',
      code: 'invalid_cursor',
    });
    expect(collectQueuePage).not.toHaveBeenCalled();
  });

  it('encodes the object next cursor returned by collectQueuePage', async () => {
    collectQueuePage.mockResolvedValue({
      items: [],
      hasMore: true,
      nextCursor: { startedAt: '2026-07-22T01:00:00.000Z', id: UUID_A },
    });
    const response = await GET(req());
    const body = await response.json();
    expect(response.status).toBe(200);
    // 외부 계약: next_cursor 는 opaque 문자열. 실제 decode 로 위치를 복원해 검증한다.
    expect(typeof body.next_cursor).toBe('string');
    expect(decodeQueueCursor(body.next_cursor)).toEqual({
      startedAt: '2026-07-22T01:00:00.000Z',
      id: UUID_A,
    });
  });

  it('returns a null next cursor as null (no more pages)', async () => {
    collectQueuePage.mockResolvedValue({ items: [], hasMore: false, nextCursor: null });
    const response = await GET(req());
    const body = await response.json();
    expect(body.next_cursor).toBeNull();
    expect(body.has_more).toBe(false);
  });

  it('orders by started_at then id and applies the composite keyset for a cursor', async () => {
    const listChain = chain({ data: [], error: null });
    from.mockReturnValue(listChain);
    // 실제 decode 를 태우도록 route 가 받은 cursor 를 fetchCandidates 로 forward.
    collectQueuePage.mockImplementation(async ({ cursor, fetchCandidates }) => {
      await fetchCandidates(cursor, 30);
      return { items: [], hasMore: false, nextCursor: null };
    });
    const cursor = encodeQueueCursor({ startedAt: '2026-07-22T01:00:00.000Z', id: UUID_A });
    const res = await GET(req(`?cursor=${cursor}`));
    expect(res.status).toBe(200);
    expect(listChain.order).toHaveBeenCalledWith('started_at', { ascending: false });
    expect(listChain.order).toHaveBeenCalledWith('id', { ascending: false });
    expect(listChain.or).toHaveBeenCalledWith(
      `started_at.lt.2026-07-22T01:00:00.000Z,and(started_at.eq.2026-07-22T01:00:00.000Z,id.lt.${UUID_A})`,
    );
  });

  it('carries a microsecond cursor into the keyset filter without truncation', async () => {
    const listChain = chain({ data: [], error: null });
    from.mockReturnValue(listChain);
    collectQueuePage.mockImplementation(async ({ cursor, fetchCandidates }) => {
      await fetchCandidates(cursor, 30);
      return { items: [], hasMore: false, nextCursor: null };
    });
    // decode 가 마이크로초를 잘라내면 keyset 경계가 .123000 으로 이동해 그 사이 행을 건너뛴다.
    const cursor = encodeQueueCursor({ startedAt: '2026-07-22T01:00:00.123456Z', id: UUID_A });
    const res = await GET(req(`?cursor=${cursor}`));
    expect(res.status).toBe(200);
    expect(listChain.or).toHaveBeenCalledWith(
      `started_at.lt.2026-07-22T01:00:00.123456Z,and(started_at.eq.2026-07-22T01:00:00.123456Z,id.lt.${UUID_A})`,
    );
  });

  it('surfaces a generic 502 on a Supabase error without leaking the cause', async () => {
    collectQueuePage.mockRejectedValue({ message: 'relation camera_clips does not exist' });
    const res = await GET(req());
    expect(res.status).toBe(502);
    const body = await res.json();
    expect(JSON.stringify(body)).not.toContain('camera_clips');
    expect(JSON.stringify(body)).not.toContain('relation');
  });
});
