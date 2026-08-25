import { afterAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

const { requireProductionLabelingAccess, from, presignGet } = vi.hoisted(() => ({
  requireProductionLabelingAccess: vi.fn(),
  from: vi.fn(),
  presignGet: vi.fn(),
}));
vi.mock('@/lib/labelingAccess', () => ({ requireProductionLabelingAccess }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { from } }));
vi.mock('@/lib/r2', () => ({ presignGet }));

import { GET } from './route';

const OWNER = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const ITEM = '11111111-1111-4111-8111-111111111111';
const BATCH = '22222222-2222-4222-8222-222222222222';
const CLIP = '33333333-3333-4333-8333-333333333333';
const TEST_SECRET = 'task6-owner-playback-token-test-secret-at-least-32-bytes';
const PREVIOUS_SECRET = process.env.SUPABASE_SERVICE_ROLE_KEY;

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

function request() {
  return new NextRequest(`https://label.tera-ai.uk/api/labeling-v3/gme-audit/owner/${ITEM}/file/url`);
}

describe('GET Owner GME audit media URL', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-08-24T00:00:00Z'));
    process.env.SUPABASE_SERVICE_ROLE_KEY = TEST_SECRET;
    requireProductionLabelingAccess.mockResolvedValue({ ok: true, userId: OWNER, isOwner: true });
    const data: Record<string, unknown[]> = {
      gme_negative_audit_items: [{ id: ITEM, batch_id: BATCH, clip_id: CLIP }],
      gme_negative_audit_batches: [{ id: BATCH }],
      gme_negative_audit_batch_events: [{ event_type: 'opened' }],
      gme_negative_audit_submissions: [{ id: '44444444-4444-4444-8444-444444444444' }],
      motion_clips: [{ r2_key: 'private/audit/source.mp4' }],
    };
    from.mockImplementation((table: string) => chain({ data: data[table], error: null }));
    presignGet.mockResolvedValue('https://media.example/signed-token');
  });

  it('returns only an opaque same-origin item path after Owner authorization', async () => {
    const response = await GET(request(), { params: { itemId: ITEM } });

    expect(response.status).toBe(200);
    expect(response.headers.get('cache-control')).toContain('no-store');
    const body = await response.json();
    expect(body.expires_in).toBe(300);
    const url = new URL(body.url, 'https://label.tera-ai.uk');
    expect(url.pathname).toBe(`/api/labeling-v3/gme-audit/owner/${ITEM}/file`);
    expect(Array.from(url.searchParams.keys())).toEqual(['token']);
    const token = url.searchParams.get('token');
    expect(token).toMatch(/^gma1\.[A-Za-z0-9_-]+$/);
    const raw = Buffer.from(String(token).slice('gma1.'.length), 'base64url').toString('utf8');
    expect(raw).not.toContain(OWNER);
    expect(raw).not.toContain(ITEM);
    expect(raw).not.toContain(TEST_SECRET);
    expect(JSON.stringify(body)).not.toMatch(/private|source\.mp4|bucket|r2_key|https:\/\//);
    expect(response.headers.get('referrer-policy')).toBe('no-referrer');
    expect(from).not.toHaveBeenCalled();
    expect(presignGet).not.toHaveBeenCalled();
  });

  it('rejects non-owner with zero DB and signer calls', async () => {
    requireProductionLabelingAccess.mockResolvedValue({ ok: true, userId: 'reviewer', isOwner: false });

    const response = await GET(request(), { params: { itemId: ITEM } });

    expect(response.status).toBe(403);
    expect(from).not.toHaveBeenCalled();
    expect(presignGet).not.toHaveBeenCalled();
  });

  it('rejects malformed item ids and query strings without downstream calls', async () => {
    let response = await GET(new NextRequest(
      'https://label.tera-ai.uk/api/labeling-v3/gme-audit/owner/not-a-uuid/file/url',
    ), { params: { itemId: 'not-a-uuid' } });
    expect(response.status).toBe(400);

    response = await GET(new NextRequest(`${request().url}?source=private`), { params: { itemId: ITEM } });
    expect(response.status).toBe(400);
    expect(from).not.toHaveBeenCalled();
    expect(presignGet).not.toHaveBeenCalled();
  });

  it('fails closed without exposing the server token secret when issuance is unavailable', async () => {
    delete process.env.SUPABASE_SERVICE_ROLE_KEY;

    const response = await GET(request(), { params: { itemId: ITEM } });

    expect(response.status).toBe(502);
    expect(await response.text()).not.toMatch(/secret|service.role|SUPABASE/i);
    expect(response.headers.get('referrer-policy')).toBe('no-referrer');
  });
});
