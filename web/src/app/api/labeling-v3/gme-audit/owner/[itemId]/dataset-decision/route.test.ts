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
const EFFECTIVE_DIGEST = 'a'.repeat(64);
const body = {
  decision: 'include_candidate',
  reason: '중복·holdout 확인을 위한 개발 후보',
  expected_effective_digest: EFFECTIVE_DIGEST,
};

function request(value: unknown) {
  return new NextRequest(`https://label.tera-ai.uk/api/labeling-v3/gme-audit/owner/${ITEM}/dataset-decision`, {
    method: 'POST', body: JSON.stringify(value), headers: { 'content-type': 'application/json' },
  });
}

describe('POST /api/labeling-v3/gme-audit/owner/[itemId]/dataset-decision', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireProductionLabelingAccess.mockResolvedValue({ ok: true, userId: OWNER, isOwner: true });
    rpc.mockResolvedValue({ data: [{ status: 'decided' }], error: null });
  });

  it('is dynamic Node/no-store and sends only the append-only RPC digest pin', async () => {
    expect(runtime).toBe('nodejs');
    expect(dynamic).toBe('force-dynamic');

    const response = await POST(request(body), { params: { itemId: ITEM } });

    expect(response.status).toBe(200);
    expect(response.headers.get('cache-control')).toContain('no-store');
    expect(await response.json()).toEqual({ status: 'decided' });
    expect(rpc).toHaveBeenCalledWith('fn_append_gme_negative_audit_dataset_decision', {
      p_item_id: ITEM,
      p_owner_id: OWNER,
      p_decision: 'include_candidate',
      p_reason: '중복·holdout 확인을 위한 개발 후보',
      p_expected_effective_digest: EFFECTIVE_DIGEST,
    });
    expect(from).not.toHaveBeenCalled();
  });

  it('rejects non-owner before every DB call', async () => {
    requireProductionLabelingAccess.mockResolvedValue({ ok: true, userId: 'labeler', isOwner: false });

    const response = await POST(request(body), { params: { itemId: ITEM } });

    expect(response.status).toBe(403);
    expect(rpc).not.toHaveBeenCalled();
    expect(from).not.toHaveBeenCalled();
  });

  it('passes auth failure and rejects extra keys, enums, reason and digest before RPC', async () => {
    requireProductionLabelingAccess.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: 'unauthorized' }, { status: 401 }),
    });
    let response = await POST(request(body), { params: { itemId: ITEM } });
    expect(response.status).toBe(401);
    expect(rpc).not.toHaveBeenCalled();

    requireProductionLabelingAccess.mockResolvedValue({ ok: true, userId: OWNER, isOwner: true });
    for (const invalid of [
      { ...body, stratum: 'random_negative' },
      { ...body, decision: 'train_now' },
      { ...body, reason: ' ' },
      { ...body, expected_effective_digest: 'bad' },
    ]) {
      rpc.mockClear();
      response = await POST(request(invalid), { params: { itemId: ITEM } });
      expect(response.status).toBe(400);
      expect(rpc).not.toHaveBeenCalled();
    }
  });

  it('maps stale, control, and missing-adjudication PT409 to public 409 without raw text', async () => {
    for (const message of ['stale_effective_digest', 'control_cannot_include_candidate', 'adjudication_required']) {
      rpc.mockResolvedValueOnce({ data: null, error: { code: 'PT409', message } });
      const response = await POST(request(body), { params: { itemId: ITEM } });
      expect(response.status).toBe(409);
      const json = JSON.stringify(await response.json());
      expect(json).not.toContain(message);
      expect(json).not.toContain(EFFECTIVE_DIGEST);
    }
  });

  it.each([
    ['22023', 400], ['PT403', 403], ['PT404', 404], ['PT410', 410], ['PT427', 410], ['08006', 502],
  ])('maps %s to stable %i', async (code, status) => {
    rpc.mockResolvedValue({ data: null, error: { code, message: 'private db error' } });
    const response = await POST(request(body), { params: { itemId: ITEM } });
    expect(response.status).toBe(status);
    expect(JSON.stringify(await response.json())).not.toContain('private db error');
  });
});
