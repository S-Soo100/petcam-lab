import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { requireProductionLabelingAccess, from, rpc } = vi.hoisted(() => ({
  requireProductionLabelingAccess: vi.fn(),
  from: vi.fn(),
  rpc: vi.fn(),
}));
vi.mock('@/lib/labelingAccess', () => ({ requireProductionLabelingAccess }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { from, rpc } }));

import { dynamic, GET, runtime } from './route';

const OWNER = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const REVIEWER = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const BATCH = '11111111-1111-4111-8111-111111111111';
const RANDOM_ITEM = '22222222-2222-4222-8222-222222222222';
const CONTROL_ITEM = '33333333-3333-4333-8333-333333333333';
const DIGEST_A = 'a'.repeat(64);
const DIGEST_B = 'b'.repeat(64);

function chain(result: { data: unknown; error: unknown }) {
  const query: Record<string, unknown> = {};
  for (const method of ['select', 'eq', 'in', 'order', 'limit']) query[method] = vi.fn(() => query);
  (query as { then: unknown }).then = (resolve: (value: unknown) => unknown) => resolve(result);
  return query;
}

function request(query = '') {
  return new NextRequest(`https://label.tera-ai.uk/api/labeling-v3/gme-audit/owner/overview${query}`);
}

function rows() {
  return {
    gme_negative_audit_batches: [{
      id: BATCH,
      batch_kind: 'calibration',
      expected_negative_count: 120,
      expected_control_count: 30,
      expected_total_count: 150,
    }],
    gme_negative_audit_items: [
      { id: RANDOM_ITEM, ordinal: 1, duration_sec: '60', stratum: 'random_negative', assigned_reviewer_id: REVIEWER },
      { id: CONTROL_ITEM, ordinal: 2, duration_sec: '30', stratum: 'positive_control', assigned_reviewer_id: REVIEWER },
    ],
    gme_negative_audit_submissions: [
      { id: '44444444-4444-4444-8444-444444444444', item_id: RANDOM_ITEM, reviewer_id: REVIEWER, verdict: 'gecko_present', representative_sec: '4.5', bbox: { x: 0.1, y: 0.2, width: 0.3, height: 0.4 }, digest: DIGEST_A },
      { id: '55555555-5555-4555-8555-555555555555', item_id: CONTROL_ITEM, reviewer_id: REVIEWER, verdict: 'uncertain', representative_sec: null, bbox: null, digest: DIGEST_B },
    ],
    gme_negative_audit_corrections: [],
    gme_negative_audit_adjudications: [],
    gme_negative_audit_dataset_decisions: [],
    gme_negative_audit_batch_events: [{ event_type: 'opened' }],
  };
}

describe('GET /api/labeling-v3/gme-audit/owner/overview', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireProductionLabelingAccess.mockResolvedValue({ ok: true, userId: OWNER, isOwner: true });
    const data = rows();
    from.mockImplementation((table: keyof typeof data) => chain({ data: data[table], error: null }));
  });

  it('is dynamic Node, no-store, and returns only the Owner allowlist', async () => {
    expect(runtime).toBe('nodejs');
    expect(dynamic).toBe('force-dynamic');

    const response = await GET(request());

    expect(response.status).toBe(200);
    expect(response.headers.get('cache-control')).toContain('no-store');
    expect(await response.json()).toEqual({
      batch_id: BATCH,
      batch_state: 'opened',
      completed: 2,
      total: 150,
      random_negative: { completed: 1, total: 120 },
      positive_control: { completed: 1, total: 30 },
      needs_adjudication: [
        {
          item_id: RANDOM_ITEM,
          ordinal: 1,
          duration_sec: 60,
          stratum: 'random_negative',
          effective_verdict: 'gecko_present',
          effective_representative_sec: 4.5,
          effective_bbox: { x: 0.1, y: 0.2, width: 0.3, height: 0.4 },
          expected_submission_digest: DIGEST_A,
        },
        {
          item_id: CONTROL_ITEM,
          ordinal: 2,
          duration_sec: 30,
          stratum: 'positive_control',
          effective_verdict: 'uncertain',
          effective_representative_sec: null,
          effective_bbox: null,
          expected_submission_digest: DIGEST_B,
        },
      ],
      dataset_decision_eligible: [],
    });
    const json = JSON.stringify(await (await GET(request())).json());
    for (const forbidden of ['reviewer_id', REVIEWER, 'assigned_reviewer_id', 'clip_id', 'source', 'r2_key', 'gme_run', 'model']) {
      expect(json).not.toContain(forbidden);
    }
  });

  it('applies the latest correction and excludes already adjudicated or absent rows', async () => {
    const data = rows();
    data.gme_negative_audit_corrections = [{
      id: '66666666-6666-4666-8666-666666666666',
      item_id: RANDOM_ITEM,
      original_submission_id: '44444444-4444-4444-8444-444444444444',
      reviewer_id: REVIEWER,
      verdict: 'gecko_absent', representative_sec: null, bbox: null,
      expected_submission_digest: DIGEST_A, digest: 'c'.repeat(64), created_at: '2026-08-23T01:00:00Z',
    }] as never[];
    data.gme_negative_audit_adjudications = [{
      id: '77777777-7777-4777-8777-777777777777', item_id: CONTROL_ITEM,
      original_submission_id: '55555555-5555-4555-8555-555555555555', owner_id: OWNER,
      final_verdict: 'gecko_absent', representative_sec: null, bbox: null,
      effective_submission_digest: DIGEST_B, digest: 'd'.repeat(64),
    }] as never[];
    from.mockImplementation((table: keyof typeof data) => chain({ data: data[table], error: null }));

    const response = await GET(request());

    expect((await response.json()).needs_adjudication).toEqual([]);
  });

  it('returns reload-safe Dataset eligibility for Owner-direct and adjudicated random items only', async () => {
    const data = rows();
    data.gme_negative_audit_items[0].assigned_reviewer_id = OWNER;
    data.gme_negative_audit_submissions[0].reviewer_id = OWNER;
    from.mockImplementation((table: keyof typeof data) => chain({ data: data[table], error: null }));
    let response = await GET(request());
    let body = await response.json();
    expect(body.needs_adjudication).toHaveLength(1);
    expect(body.dataset_decision_eligible).toEqual([{
      item_id: RANDOM_ITEM,
      ordinal: 1,
      duration_sec: 60,
      stratum: 'random_negative',
      effective_verdict: 'gecko_present',
      effective_representative_sec: 4.5,
      effective_bbox: { x: 0.1, y: 0.2, width: 0.3, height: 0.4 },
      expected_effective_digest: DIGEST_A,
    }]);

    data.gme_negative_audit_items[0].assigned_reviewer_id = REVIEWER;
    data.gme_negative_audit_submissions[0].reviewer_id = REVIEWER;
    data.gme_negative_audit_adjudications = [{
      id: '66666666-6666-4666-8666-666666666666', item_id: RANDOM_ITEM,
      original_submission_id: '44444444-4444-4444-8444-444444444444', owner_id: OWNER,
      final_verdict: 'gecko_present', representative_sec: '5',
      bbox: { x: 0.2, y: 0.2, width: 0.2, height: 0.2 },
      effective_submission_digest: DIGEST_A, digest: 'c'.repeat(64),
    }] as never[];
    from.mockImplementation((table: keyof typeof data) => chain({ data: data[table], error: null }));
    response = await GET(request());
    body = await response.json();
    expect(body.needs_adjudication.map((item: { item_id: string }) => item.item_id)).not.toContain(RANDOM_ITEM);
    expect(body.dataset_decision_eligible[0]).toMatchObject({
      item_id: RANDOM_ITEM, effective_verdict: 'gecko_present', expected_effective_digest: 'c'.repeat(64),
    });

    data.gme_negative_audit_dataset_decisions = [{ item_id: RANDOM_ITEM }] as never[];
    from.mockImplementation((table: keyof typeof data) => chain({ data: data[table], error: null }));
    response = await GET(request());
    expect((await response.json()).dataset_decision_eligible).toEqual([]);
  });

  it('reports only opened lifecycle and rejects a closed latest batch', async () => {
    const data = rows();
    data.gme_negative_audit_batch_events = [{ event_type: 'closed' }];
    from.mockImplementation((table: keyof typeof data) => chain({ data: data[table], error: null }));

    const response = await GET(request());

    expect(response.status).toBe(410);
    expect(await response.json()).toEqual({ detail: '점검이 종료됐어.', code: 'batch_closed' });
  });

  it('rejects non-owner before every database call with stable 403', async () => {
    requireProductionLabelingAccess.mockResolvedValue({ ok: true, userId: REVIEWER, isOwner: false });

    const response = await GET(request());

    expect(response.status).toBe(403);
    expect(await response.json()).toEqual({ detail: 'Owner만 접근할 수 있어.', code: 'owner_required' });
    expect(from).not.toHaveBeenCalled();
    expect(rpc).not.toHaveBeenCalled();
  });

  it('passes auth rejection before DB and rejects query fields before DB', async () => {
    requireProductionLabelingAccess.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: 'unauthorized' }, { status: 401 }),
    });
    let response = await GET(request());
    expect(response.status).toBe(401);
    expect(from).not.toHaveBeenCalled();

    requireProductionLabelingAccess.mockResolvedValue({ ok: true, userId: OWNER, isOwner: true });
    response = await GET(request('?batch_id=forged'));
    expect(response.status).toBe(400);
    expect(from).not.toHaveBeenCalled();
  });

  it('fails malformed or errored private rows as stable 502 without raw DB text', async () => {
    from.mockImplementation((table: string) => chain({
      data: table === 'gme_negative_audit_batches' ? rows().gme_negative_audit_batches : null,
      error: table === 'gme_negative_audit_batches' ? null : { code: '08006', message: 'secret reviewer query failed' },
    }));

    const response = await GET(request());

    expect(response.status).toBe(502);
    expect(JSON.stringify(await response.json())).not.toContain('secret');
  });

  it('loads child ledgers through frozen item ids because child tables have no batch_id', async () => {
    const data = rows();
    from.mockImplementation((table: keyof typeof data) => {
      const operations: Array<[string, ...unknown[]]> = [];
      const query: Record<string, unknown> = {};
      for (const method of ['select', 'eq', 'in', 'order', 'limit']) {
        query[method] = vi.fn((...args: unknown[]) => {
          operations.push([method, ...args]);
          return query;
        });
      }
      (query as { then: unknown }).then = (resolve: (value: unknown) => unknown) => {
        const child = [
          'gme_negative_audit_submissions', 'gme_negative_audit_corrections',
          'gme_negative_audit_adjudications', 'gme_negative_audit_dataset_decisions',
        ].includes(table);
        const invalidBatchFilter = child && operations.some(([method, column]) => method === 'eq' && column === 'batch_id');
        const itemJoin = operations.some(([method, column]) => method === 'in' && column === 'item_id');
        return resolve(invalidBatchFilter || (child && !itemJoin)
          ? { data: null, error: { code: '42703', message: 'column batch_id does not exist' } }
          : { data: data[table], error: null });
      };
      return query;
    });

    const response = await GET(request());

    expect(response.status).toBe(200);
    expect((await response.json()).completed).toBe(2);
  });
});
