import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { requireProductionLabelingAccess, rpc } = vi.hoisted(() => ({
  requireProductionLabelingAccess: vi.fn(),
  rpc: vi.fn(),
}));
vi.mock('@/lib/labelingAccess', () => ({ requireProductionLabelingAccess }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));

import { dynamic, GET, runtime } from './route';

function request(query = '') {
  return new NextRequest(`https://label.tera-ai.uk/api/labeling-v3/gme-audit/queue${query}`);
}

function privateRow(overrides: Record<string, unknown> = {}) {
  return {
    item_id: '11111111-1111-4111-8111-111111111111',
    ordinal: 1,
    captured_at: '2026-08-23T10:00:00Z',
    duration_sec: '60',
    media_ready: true,
    submitted: false,
    completed: 2,
    total: 5,
    stratum: 'positive_control',
    gme_run_id: 'hidden-run',
    media_sha256: 'hidden-hash',
    ...overrides,
  };
}

describe('GET /api/labeling-v3/gme-audit/queue', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireProductionLabelingAccess.mockResolvedValue({
      ok: true,
      userId: 'bearer-reviewer',
      isOwner: false,
    });
    rpc.mockResolvedValue({ data: [privateRow()], error: null });
  });

  it('is a dynamic Node route and returns no-store', async () => {
    expect(runtime).toBe('nodejs');
    expect(dynamic).toBe('force-dynamic');
    const response = await GET(request());
    expect(response.headers.get('cache-control')).toContain('no-store');
  });

  it('uses only the bearer-derived reviewer id and rejects reviewer query fields', async () => {
    const forged = await GET(request('?reviewer_id=other'));
    expect(forged.status).toBe(400);
    expect(rpc).not.toHaveBeenCalled();

    const forgedHeader = new NextRequest(
      'https://label.tera-ai.uk/api/labeling-v3/gme-audit/queue',
      { headers: { 'x-reviewer-id': 'other' } },
    );
    await GET(forgedHeader);
    expect(rpc).toHaveBeenCalledWith('fn_list_gme_negative_audit_queue', {
      p_reviewer_id: 'bearer-reviewer',
    });
  });

  it('returns the exact blind queue allowlist and top-level progress', async () => {
    const response = await GET(request());
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({
      items: [
        {
          item_id: '11111111-1111-4111-8111-111111111111',
          ordinal: 1,
          captured_at: '2026-08-23T10:00:00Z',
          duration_sec: 60,
          media_ready: true,
          submitted: false,
        },
      ],
      completed: 2,
      total: 5,
    });
    const json = JSON.stringify(await (await GET(request())).json());
    for (const forbidden of ['stratum', 'gme_run_id', 'media_sha256', 'control']) {
      expect(json).not.toContain(forbidden);
    }
  });

  it('passes auth failures through with no-store and never calls RPC', async () => {
    requireProductionLabelingAccess.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: 'unauthorized' }, { status: 401 }),
    });
    const response = await GET(request());
    expect(response.status).toBe(401);
    expect(response.headers.get('cache-control')).toContain('no-store');
    expect(rpc).not.toHaveBeenCalled();
  });

  it('maps DB failure to stable 502 without raw message', async () => {
    rpc.mockResolvedValue({ data: null, error: { code: '08006', message: 'secret table failed' } });
    const response = await GET(request());
    expect(response.status).toBe(502);
    expect(JSON.stringify(await response.json())).not.toContain('secret');
  });
});
