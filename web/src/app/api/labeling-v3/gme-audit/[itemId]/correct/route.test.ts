import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { requireProductionLabelingAccess, requireAuditAssignment, rpc } = vi.hoisted(() => ({
  requireProductionLabelingAccess: vi.fn(),
  requireAuditAssignment: vi.fn(),
  rpc: vi.fn(),
}));
vi.mock('@/lib/labelingAccess', () => ({ requireProductionLabelingAccess }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));
vi.mock('@/lib/gmeNegativeAuditServer', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/gmeNegativeAuditServer')>()),
  requireAuditAssignment,
}));

import { dynamic, POST, runtime } from './route';

const ITEM = '11111111-1111-4111-8111-111111111111';
const correction = {
  verdict: 'gecko_present',
  representative_sec: 4.2,
  bbox: { x: 0.1, y: 0.2, width: 0.3, height: 0.4 },
  reason: 'bbox correction',
  revision: 'own-opaque-revision',
};

function request(body: unknown) {
  return new NextRequest(
    `https://label.tera-ai.uk/api/labeling-v3/gme-audit/${ITEM}/correct`,
    { method: 'POST', body: JSON.stringify(body), headers: { 'content-type': 'application/json' } },
  );
}

describe('POST /api/labeling-v3/gme-audit/[itemId]/correct', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireProductionLabelingAccess.mockResolvedValue({
      ok: true,
      userId: 'bearer-reviewer',
      isOwner: false,
    });
    requireAuditAssignment.mockResolvedValue({
      ok: true,
      row: { duration_sec: '60', initial_verdict: 'gecko_absent' },
    });
    rpc.mockResolvedValue({ data: [{ status: 'corrected' }], error: null });
  });

  it('is dynamic Node and maps public revision to the internal RPC pin', async () => {
    expect(runtime).toBe('nodejs');
    expect(dynamic).toBe('force-dynamic');
    const response = await POST(request(correction), { params: { itemId: ITEM } });
    expect(response.status).toBe(200);
    expect(response.headers.get('cache-control')).toContain('no-store');
    expect(await response.json()).toEqual({ status: 'corrected' });
    expect(rpc).toHaveBeenCalledTimes(1);
    expect(rpc).toHaveBeenCalledWith('fn_append_gme_negative_audit_correction', {
      p_item_id: ITEM,
      p_reviewer_id: 'bearer-reviewer',
      p_verdict: 'gecko_present',
      p_representative_sec: 4.2,
      p_bbox: { x: 0.1, y: 0.2, width: 0.3, height: 0.4 },
      p_reason: 'bbox correction',
      p_expected_submission_digest: 'own-opaque-revision',
    });
  });

  it('rejects internal digest/reviewer keys on the public wire', async () => {
    for (const extra of [
      { expected_submission_digest: 'forged' },
      { submission_digest: 'forged' },
      { reviewer_id: 'other' },
    ]) {
      rpc.mockClear();
      const response = await POST(request({ ...correction, ...extra }), {
        params: { itemId: ITEM },
      });
      expect(response.status).toBe(400);
      expect(requireAuditAssignment).not.toHaveBeenCalled();
      expect(rpc).not.toHaveBeenCalled();
      requireAuditAssignment.mockClear();
    }
  });

  it('requires own initial submission and hides wrong reviewer as 404', async () => {
    requireAuditAssignment.mockResolvedValue({
      ok: true,
      row: { duration_sec: '60', initial_verdict: null },
    });
    let response = await POST(request(correction), { params: { itemId: ITEM } });
    expect(response.status).toBe(404);
    expect(rpc).not.toHaveBeenCalled();

    requireAuditAssignment.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: '대상을 찾을 수 없어.', code: 'not_assigned' }, { status: 404 }),
    });
    response = await POST(request(correction), { params: { itemId: ITEM } });
    expect(response.status).toBe(404);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('maps stale revision to stable 409 without leaking the revision or DB text', async () => {
    rpc.mockResolvedValue({ data: null, error: { code: 'PT409', message: 'stale secret row' } });
    const response = await POST(request(correction), { params: { itemId: ITEM } });
    expect(response.status).toBe(409);
    const body = await response.json();
    expect(body.code).toBe('stale_revision');
    const json = JSON.stringify(body);
    expect(json).not.toContain('own-opaque-revision');
    expect(json).not.toContain('secret');
  });

  it('maps a closed batch to 410 and never updates the original submission', async () => {
    rpc.mockResolvedValue({ data: null, error: { code: 'PT427', message: 'closed raw' } });
    const response = await POST(request(correction), { params: { itemId: ITEM } });
    expect(response.status).toBe(410);
    expect(rpc.mock.calls.map((call) => call[0])).toEqual([
      'fn_append_gme_negative_audit_correction',
    ]);
  });
});
