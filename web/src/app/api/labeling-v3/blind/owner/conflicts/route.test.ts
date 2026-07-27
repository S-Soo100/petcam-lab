import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { requireOwner, rpc, from, queryCalls } = vi.hoisted(() => ({
  requireOwner: vi.fn(),
  rpc: vi.fn(),
  from: vi.fn(),
  queryCalls: [] as { table: string; method: string; args: unknown[] }[],
}));
vi.mock('@/lib/labelingAccess', () => ({ requireOwner }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc, from } }));

import { GET } from './route';

const CLIP = '11111111-1111-4111-8111-111111111111';
const COHORT = '22222222-2222-4222-8222-222222222222';

function builder(table: string, result: unknown) {
  const b: Record<string, unknown> = {};
  for (const method of ['select', 'eq', 'is', 'in', 'or', 'order', 'limit']) {
    b[method] = (...args: unknown[]) => {
      queryCalls.push({ table, method, args });
      return b;
    };
  }
  b.then = (resolve: (value: unknown) => unknown) => Promise.resolve(result).then(resolve);
  return b;
}

function setTables(tables: Record<string, unknown>) {
  from.mockImplementation((table: string) =>
    builder(table, tables[table] ?? { data: [], error: null }),
  );
}

function req(qs = '') {
  return new NextRequest(`https://label.tera-ai.uk/api/labeling-v3/blind/owner/conflicts${qs}`);
}

describe('GET owner/conflicts', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    queryCalls.length = 0;
    requireOwner.mockResolvedValue({ ok: true, userId: 'owner' });
    rpc.mockResolvedValue({
      data: [{ clip_id: CLIP, camera_name: '2번', started_at: 't', differing_fields: ['primary_action'], updated_at: '2026-07-22T00:00:00Z' }],
      error: null,
    });
    setTables({
      motion_blind_review_cohorts: {
        data: [{ id: COHORT, status: 'open', kind: 'canary' }],
        error: null,
      },
      motion_clip_consensus: {
        data: [{
          clip_id: CLIP,
          differing_fields: ['primary_action'],
          updated_at: '2026-07-22T00:00:00Z',
        }],
        error: null,
      },
      motion_clips: {
        data: [{ id: CLIP, started_at: 't', cameras: { name: 'Canary 카메라' } }],
        error: null,
      },
    });
  });

  it('403 for a labeler (requireOwner gate)', async () => {
    requireOwner.mockResolvedValue({ ok: false, response: NextResponse.json({ detail: 'forbidden' }, { status: 403 }) });
    expect((await GET(req())).status).toBe(403);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('lists conflicts via the conflict-only RPC', async () => {
    const res = await GET(req());
    expect(res.status).toBe(200);
    expect(rpc.mock.calls[0][0]).toBe('fn_list_motion_blind_conflicts');
    const body = await res.json();
    expect(body.items[0].id).toBe(CLIP);
    expect(body.items[0].differing_fields).toEqual(['primary_action']);
  });

  it('lists exactly one selected canary cohort without using the live RPC', async () => {
    const res = await GET(req(`?cohort_id=${COHORT}`));
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.items).toEqual([
      {
        id: CLIP,
        camera_name: 'Canary 카메라',
        started_at: 't',
        differing_fields: ['primary_action'],
        updated_at: '2026-07-22T00:00:00Z',
      },
    ]);
    expect(rpc).not.toHaveBeenCalled();
    expect(queryCalls).toContainEqual({
      table: 'motion_clip_consensus',
      method: 'eq',
      args: ['cohort_kind', 'canary'],
    });
    expect(queryCalls).toContainEqual({
      table: 'motion_clip_consensus',
      method: 'eq',
      args: ['cohort_id', COHORT],
    });
    expect(queryCalls).toContainEqual({
      table: 'motion_clip_consensus',
      method: 'eq',
      args: ['status', 'conflict'],
    });
  });

  it('fails closed for a malformed or missing canary cohort', async () => {
    expect((await GET(req('?cohort_id=nope'))).status).toBe(400);
    expect(rpc).not.toHaveBeenCalled();

    setTables({ motion_blind_review_cohorts: { data: [], error: null } });
    expect((await GET(req(`?cohort_id=${COHORT}`))).status).toBe(404);
    expect(rpc).not.toHaveBeenCalled();
    expect(from).toHaveBeenCalledTimes(1);
  });

  it('rejects a malformed cursor before RPC', async () => {
    const res = await GET(req('?cursor=%%%bad'));
    expect(res.status).toBe(400);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('maps unknown DB error to 502 without raw text', async () => {
    rpc.mockResolvedValue({ data: null, error: { code: '08006', message: 'motion_clip_consensus lost' } });
    const res = await GET(req());
    expect(res.status).toBe(502);
    expect(JSON.stringify(await res.json())).not.toContain('motion_clip_consensus');
  });
});
