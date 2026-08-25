import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { requireProductionLabelingAccess, rpc, from } = vi.hoisted(() => ({
  requireProductionLabelingAccess: vi.fn(),
  rpc: vi.fn(),
  from: vi.fn(),
}));
vi.mock('@/lib/labelingAccess', () => ({ requireProductionLabelingAccess }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc, from } }));

import { dynamic, POST, runtime } from './route';

const ITEM = '11111111-1111-4111-8111-111111111111';
const OWNER = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const SUBMISSION_DIGEST = 'a'.repeat(64);
const ADJUDICATION_DIGEST = 'b'.repeat(64);
const body = {
  final_verdict: 'gecko_present',
  representative_sec: 4.2,
  bbox: { x: 0.1, y: 0.2, width: 0.3, height: 0.4 },
  reason: 'Owner가 영상을 다시 확인함',
  expected_submission_digest: SUBMISSION_DIGEST,
};

function chain(result: { data: unknown; error: unknown }) {
  const query: Record<string, unknown> = {};
  for (const method of ['select', 'eq', 'limit']) query[method] = vi.fn(() => query);
  (query as { then: unknown }).then = (resolve: (value: unknown) => unknown) => resolve(result);
  return query;
}

function request(value: unknown, contentType = 'application/json') {
  return new NextRequest(`https://label.tera-ai.uk/api/labeling-v3/gme-audit/owner/${ITEM}/adjudicate`, {
    method: 'POST',
    body: JSON.stringify(value),
    headers: { 'content-type': contentType },
  });
}

describe('POST /api/labeling-v3/gme-audit/owner/[itemId]/adjudicate', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireProductionLabelingAccess.mockResolvedValue({ ok: true, userId: OWNER, isOwner: true });
    rpc.mockResolvedValue({ data: [{ adjudication_id: '22222222-2222-4222-8222-222222222222', status: 'adjudicated', digest: ADJUDICATION_DIGEST }], error: null });
  });

  it('is dynamic Node/no-store and pins the exact effective submission digest internally', async () => {
    expect(runtime).toBe('nodejs');
    expect(dynamic).toBe('force-dynamic');

    const response = await POST(request(body), { params: { itemId: ITEM } });

    expect(response.status).toBe(200);
    expect(response.headers.get('cache-control')).toContain('no-store');
    expect(await response.json()).toEqual({ status: 'adjudicated', effective_digest: ADJUDICATION_DIGEST });
    expect(rpc).toHaveBeenCalledWith('fn_append_gme_negative_audit_adjudication', {
      p_item_id: ITEM,
      p_owner_id: OWNER,
      p_final_verdict: 'gecko_present',
      p_representative_sec: 4.2,
      p_bbox: { x: 0.1, y: 0.2, width: 0.3, height: 0.4 },
      p_reason: 'Owner가 영상을 다시 확인함',
      p_expected_submission_digest: SUBMISSION_DIGEST,
    });
    expect(from).not.toHaveBeenCalled();
  });

  it('rejects non-owner before body parsing and every DB call', async () => {
    requireProductionLabelingAccess.mockResolvedValue({ ok: true, userId: 'labeler', isOwner: false });

    const response = await POST(request(body), { params: { itemId: ITEM } });

    expect(response.status).toBe(403);
    expect(rpc).not.toHaveBeenCalled();
    expect(from).not.toHaveBeenCalled();
  });

  it('passes auth failure before DB and requires bounded application/json exact keys', async () => {
    requireProductionLabelingAccess.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: 'unauthorized' }, { status: 401 }),
    });
    let response = await POST(request(body), { params: { itemId: ITEM } });
    expect(response.status).toBe(401);
    expect(rpc).not.toHaveBeenCalled();

    requireProductionLabelingAccess.mockResolvedValue({ ok: true, userId: OWNER, isOwner: true });
    for (const invalid of [
      { ...body, reviewer_id: 'forged' },
      { ...body, expected_submission_digest: 'not-a-digest' },
      { ...body, bbox: { x: Number.NaN, y: 0, width: 1, height: 1 } },
      { ...body, final_verdict: 'gecko_absent' },
    ]) {
      rpc.mockClear();
      response = await POST(request(invalid), { params: { itemId: ITEM } });
      expect(response.status).toBe(400);
      expect(rpc).not.toHaveBeenCalled();
    }
    response = await POST(request(body, 'text/plain'), { params: { itemId: ITEM } });
    expect(response.status).toBe(400);
    expect(rpc).not.toHaveBeenCalled();
  });

  it.each([
    ['22023', 400],
    ['PT403', 403],
    ['PT404', 404],
    ['PT409', 409],
    ['PT410', 410],
    ['PT427', 410],
    ['08006', 502],
  ])('maps %s to stable %i without raw DB errors', async (code, status) => {
    rpc.mockResolvedValue({ data: null, error: { code, message: 'secret row and digest' } });

    const response = await POST(request(body), { params: { itemId: ITEM } });

    expect(response.status).toBe(status);
    expect(JSON.stringify(await response.json())).not.toContain('secret');
    expect(from).not.toHaveBeenCalled();
  });
});
