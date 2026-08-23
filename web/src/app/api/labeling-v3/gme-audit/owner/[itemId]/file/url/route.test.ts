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

  it('presigns only after Owner, item, owned batch, and opened lifecycle checks', async () => {
    const response = await GET(request(), { params: { itemId: ITEM } });

    expect(response.status).toBe(200);
    expect(response.headers.get('cache-control')).toContain('no-store');
    expect(await response.json()).toEqual({ url: 'https://media.example/signed-token', expires_in: 300 });
    expect(from.mock.calls.map(([table]) => table)).toEqual([
      'gme_negative_audit_items',
      'gme_negative_audit_batches',
      'gme_negative_audit_batch_events',
      'gme_negative_audit_submissions',
      'motion_clips',
    ]);
    expect(presignGet).toHaveBeenCalledWith('private/audit/source.mp4', 300);
    expect(JSON.stringify(await (await GET(request(), { params: { itemId: ITEM } })).json())).not.toContain('r2_key');
  });

  it('rejects non-owner with zero DB and signer calls', async () => {
    requireProductionLabelingAccess.mockResolvedValue({ ok: true, userId: 'reviewer', isOwner: false });

    const response = await GET(request(), { params: { itemId: ITEM } });

    expect(response.status).toBe(403);
    expect(from).not.toHaveBeenCalled();
    expect(presignGet).not.toHaveBeenCalled();
  });

  it('does not presign a closed or ineligible item and hides DB errors', async () => {
    from.mockImplementation((table: string) => chain({
      data: table === 'gme_negative_audit_items'
        ? [{ id: ITEM, batch_id: BATCH, clip_id: CLIP }]
        : table === 'gme_negative_audit_batches'
          ? [{ id: BATCH }]
          : table === 'gme_negative_audit_batch_events'
            ? [{ event_type: 'closed' }]
            : [],
      error: null,
    }));
    let response = await GET(request(), { params: { itemId: ITEM } });
    expect(response.status).toBe(410);
    expect(presignGet).not.toHaveBeenCalled();

    from.mockImplementation(() => chain({ data: null, error: { message: 'secret r2 failure' } }));
    response = await GET(request(), { params: { itemId: ITEM } });
    expect(response.status).toBe(502);
    expect(JSON.stringify(await response.json())).not.toContain('secret');
  });
});
