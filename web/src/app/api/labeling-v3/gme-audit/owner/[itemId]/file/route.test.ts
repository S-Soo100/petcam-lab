import { beforeEach, describe, expect, it, vi } from 'vitest';
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

const OWNER = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const ITEM = '11111111-1111-4111-8111-111111111111';
const BATCH = '22222222-2222-4222-8222-222222222222';
const CLIP = '33333333-3333-4333-8333-333333333333';
const PROVIDER_URL = 'https://bucket.r2.example/private/audit/source.mp4?signature=secret';

function chain(result: { data: unknown; error: unknown }) {
  const query: Record<string, unknown> = {};
  for (const method of ['select', 'eq', 'order', 'limit']) query[method] = vi.fn(() => query);
  (query as { then: unknown }).then = (resolve: (value: unknown) => unknown) => resolve(result);
  return query;
}

function request(range?: string) {
  return new NextRequest(
    `https://label.tera-ai.uk/api/labeling-v3/gme-audit/owner/${ITEM}/file`,
    { headers: range ? { Range: range } : undefined },
  );
}

describe('GET Owner GME audit same-origin media bytes', () => {
  beforeEach(() => {
    vi.clearAllMocks();
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
