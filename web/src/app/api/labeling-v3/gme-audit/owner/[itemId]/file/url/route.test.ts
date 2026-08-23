import { beforeEach, describe, expect, it, vi } from 'vitest';
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
    expect(body).toEqual({
      url: `/api/labeling-v3/gme-audit/owner/${ITEM}/file`,
      expires_in: 300,
    });
    expect(JSON.stringify(body)).not.toMatch(/private|source\.mp4|bucket|r2_key|https:\/\//);
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
});
