import { afterAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

const { requireProductionLabelingAccess, from, presignGet, upstreamFetch } = vi.hoisted(() => ({
  requireProductionLabelingAccess: vi.fn(),
  from: vi.fn(),
  presignGet: vi.fn(),
  upstreamFetch: vi.fn(),
}));
vi.mock('@/lib/labelingAccess', () => ({ requireProductionLabelingAccess }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { from } }));
vi.mock('@/lib/r2', () => ({ presignGet }));

import { GET } from './route';
import { GET as GET_URL } from './url/route';

const OWNER = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const ITEM = '11111111-1111-4111-8111-111111111111';
const BATCH = '22222222-2222-4222-8222-222222222222';
const CLIP = '33333333-3333-4333-8333-333333333333';
const PROVIDER_URL = 'https://bucket.r2.example/private/audit/source.mp4?signature=secret';
const TEST_SECRET = 'task6-native-video-auth-secret-at-least-32-bytes';
const PREVIOUS_SECRET = process.env.SUPABASE_SERVICE_ROLE_KEY;
const MAX_CHUNK = 8 * 1024 * 1024;

afterAll(() => {
  if (PREVIOUS_SECRET === undefined) delete process.env.SUPABASE_SERVICE_ROLE_KEY;
  else process.env.SUPABASE_SERVICE_ROLE_KEY = PREVIOUS_SECRET;
  vi.useRealTimers();
});

function chain(result: { data: unknown; error: unknown }) {
  const query: Record<string, unknown> = {};
  for (const method of ['select', 'eq', 'order', 'limit']) query[method] = vi.fn(() => query);
  (query as { then: unknown }).then = (resolve: (value: unknown) => unknown) => resolve(result);
  return query;
}

function request(range?: string, url = `https://label.tera-ai.uk/api/labeling-v3/gme-audit/owner/${ITEM}/file`) {
  return new NextRequest(
    url,
    { headers: range ? { Range: range } : undefined },
  );
}

async function nativePlaybackUrl(): Promise<string> {
  const response = await GET_URL(new NextRequest(
    `https://label.tera-ai.uk/api/labeling-v3/gme-audit/owner/${ITEM}/file/url`,
  ), { params: { itemId: ITEM } });
  const body = await response.json();
  return new URL(body.url, 'https://label.tera-ai.uk').toString();
}

describe('GET Owner GME audit same-origin media bytes', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-08-24T00:00:00Z'));
    process.env.SUPABASE_SERVICE_ROLE_KEY = TEST_SECRET;
    vi.stubGlobal('fetch', upstreamFetch);
    requireProductionLabelingAccess.mockResolvedValue({ ok: true, userId: OWNER, isOwner: true });
    const data: Record<string, unknown[]> = {
      gme_negative_audit_items: [{ id: ITEM, batch_id: BATCH, clip_id: CLIP }],
      gme_negative_audit_batches: [{ id: BATCH }],
      gme_negative_audit_batch_events: [{ event_type: 'opened' }],
      gme_negative_audit_submissions: [{ id: '44444444-4444-4444-8444-444444444444' }],
      motion_clips: [{ r2_key: 'private/audit/source.mp4' }],
    };
    from.mockImplementation((table: string) => chain({ data: data[table], error: null }));
    presignGet.mockResolvedValue(PROVIDER_URL);
    upstreamFetch.mockResolvedValue(new Response('video-bytes', {
      status: 206,
      headers: {
        'content-type': 'video/mp4',
        'content-length': '11',
        'content-range': 'bytes 0-10/100',
        'accept-ranges': 'bytes',
        location: 'https://bucket.r2.example/private/audit/source.mp4',
        'x-amz-meta-source': 'private/audit/source.mp4',
      },
    }));
  });

  it('reauthorizes Range requests and forwards only safe video status and headers', async () => {
    const response = await GET(request('bytes=0-10'), { params: { itemId: ITEM } });

    expect(response.status).toBe(206);
    expect(await response.text()).toBe('video-bytes');
    expect(response.headers.get('content-type')).toBe('video/mp4');
    expect(response.headers.get('content-range')).toBe('bytes 0-10/100');
    expect(response.headers.get('accept-ranges')).toBe('bytes');
    expect(response.headers.get('cache-control')).toContain('no-store');
    expect(response.headers.get('referrer-policy')).toBe('no-referrer');
    expect(response.headers.get('location')).toBeNull();
    expect(response.headers.get('x-amz-meta-source')).toBeNull();
    const publicHeaders: Array<[string, string]> = [];
    response.headers.forEach((value, key) => publicHeaders.push([key, value]));
    expect(JSON.stringify(publicHeaders)).not.toMatch(/bucket|r2|source\.mp4|private\/audit/i);
    expect(upstreamFetch).toHaveBeenCalledWith(PROVIDER_URL, {
      headers: { Range: 'bytes=0-10' },
      redirect: 'error',
      cache: 'no-store',
    });
  });

  it('serves native video GET/Range with only the short-lived opaque token', async () => {
    const url = await nativePlaybackUrl();
    requireProductionLabelingAccess.mockClear();

    const response = await GET(request('bytes=0-10', url), { params: { itemId: ITEM } });

    expect(response.status).toBe(206);
    expect(await response.text()).toBe('video-bytes');
    expect(requireProductionLabelingAccess).not.toHaveBeenCalled();
    expect(from).toHaveBeenCalled();
    expect(presignGet).toHaveBeenCalledOnce();
  });

  it.each(['tampered', 'expired', 'wrong-item', 'rotated-key'])(
    'rejects %s playback tokens before DB, signer, and upstream',
    async (kind) => {
      let url = await nativePlaybackUrl();
      requireProductionLabelingAccess.mockClear();
      from.mockClear();
      presignGet.mockClear();
      upstreamFetch.mockClear();
      if (kind === 'tampered') url = `${url.slice(0, -1)}${url.endsWith('A') ? 'B' : 'A'}`;
      if (kind === 'expired') vi.advanceTimersByTime(301_000);
      if (kind === 'wrong-item') {
        url = url.replace(ITEM, '99999999-9999-4999-8999-999999999999');
      }
      if (kind === 'rotated-key') process.env.SUPABASE_SERVICE_ROLE_KEY = `${TEST_SECRET}-rotated`;

      const routeItem = kind === 'wrong-item' ? '99999999-9999-4999-8999-999999999999' : ITEM;
      const response = await GET(request('bytes=0-10', url), { params: { itemId: routeItem } });

      expect(response.status).toBe(403);
      expect(requireProductionLabelingAccess).not.toHaveBeenCalled();
      expect(from).not.toHaveBeenCalled();
      expect(presignGet).not.toHaveBeenCalled();
      expect(upstreamFetch).not.toHaveBeenCalled();
      expect(await response.text()).not.toMatch(/owner|item|secret|bucket|r2|source\.mp4/i);
    },
  );

  it.each([
    `bytes=0-${MAX_CHUNK}`,
    `bytes=-${MAX_CHUNK + 1}`,
    'bytes=0-1,4-5',
    `bytes=${'9'.repeat(40)}-`,
    'bytes=10-9',
  ])('rejects invalid or oversized client Range %s before upstream', async (range) => {
    const response = await GET(request(range), { params: { itemId: ITEM } });

    expect(response.status).toBe(416);
    expect(upstreamFetch).not.toHaveBeenCalled();
  });

  it.each([
    [undefined, `bytes=0-${MAX_CHUNK - 1}`],
    ['bytes=123-', `bytes=123-${123 + MAX_CHUNK - 1}`],
    [`bytes=-${MAX_CHUNK}`, `bytes=-${MAX_CHUNK}`],
  ])('rewrites missing/open-ended Range to one bounded upstream chunk', async (range, expected) => {
    await GET(request(range), { params: { itemId: ITEM } });

    expect(upstreamFetch).toHaveBeenCalledWith(PROVIDER_URL, {
      headers: { Range: expected },
      redirect: 'error',
      cache: 'no-store',
    });
  });

  it.each([
    ['ignored Range 200', new Response('unbounded', {
      status: 200,
      headers: { 'content-type': 'video/mp4', 'content-length': '9' },
    })],
    ['oversized 206', new Response('oversized', {
      status: 206,
      headers: {
        'content-type': 'video/mp4',
        'content-length': String(MAX_CHUNK + 1),
        'content-range': `bytes 0-${MAX_CHUNK}/${MAX_CHUNK + 1}`,
      },
    })],
    ['mismatched 206', new Response('short', {
      status: 206,
      headers: {
        'content-type': 'video/mp4',
        'content-length': '5',
        'content-range': 'bytes 0-10/100',
      },
    })],
  ])('rejects and cancels unsafe upstream response: %s', async (_label, upstream) => {
    const cancel = vi.spyOn(upstream.body!, 'cancel');
    upstreamFetch.mockResolvedValue(upstream);

    const response = await GET(request('bytes=0-10'), { params: { itemId: ITEM } });

    expect(response.status).toBe(502);
    expect(cancel).toHaveBeenCalledOnce();
  });

  it('rejects non-owner with zero DB, signer, and upstream fetch calls', async () => {
    requireProductionLabelingAccess.mockResolvedValue({ ok: true, userId: 'reviewer', isOwner: false });

    const response = await GET(request(), { params: { itemId: ITEM } });

    expect(response.status).toBe(403);
    expect(from).not.toHaveBeenCalled();
    expect(presignGet).not.toHaveBeenCalled();
    expect(upstreamFetch).not.toHaveBeenCalled();
  });

  it('does not redirect or leak an upstream provider error', async () => {
    upstreamFetch.mockResolvedValue(new Response('secret bucket failure', {
      status: 302,
      headers: { location: PROVIDER_URL },
    }));

    const response = await GET(request(), { params: { itemId: ITEM } });

    expect(response.status).toBe(502);
    expect(response.headers.get('location')).toBeNull();
    const body = await response.text();
    expect(body).not.toMatch(/secret|bucket|source\.mp4|private\/audit/i);
  });

  it('forwards an unsatisfied Range status without the provider error body', async () => {
    upstreamFetch.mockResolvedValue(new Response('private bucket diagnostic', {
      status: 416,
      headers: { 'content-range': 'bytes */100', location: PROVIDER_URL },
    }));

    const response = await GET(request('bytes=1000-2000'), { params: { itemId: ITEM } });

    expect(response.status).toBe(416);
    expect(response.headers.get('content-range')).toBe('bytes */100');
    expect(response.headers.get('location')).toBeNull();
    expect(await response.text()).toBe('');
  });
});
