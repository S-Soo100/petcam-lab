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
const present = {
  verdict: 'gecko_present',
  representative_sec: 4.2,
  bbox: { x: 0.1, y: 0.2, width: 0.3, height: 0.4 },
};

function request(body: unknown, query = '') {
  return new NextRequest(
    `https://label.tera-ai.uk/api/labeling-v3/gme-audit/${ITEM}/submit${query}`,
    { method: 'POST', body: JSON.stringify(body), headers: { 'content-type': 'application/json' } },
  );
}

describe('POST /api/labeling-v3/gme-audit/[itemId]/submit', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireProductionLabelingAccess.mockResolvedValue({
      ok: true,
      userId: 'bearer-reviewer',
      isOwner: false,
    });
    requireAuditAssignment.mockResolvedValue({
      ok: true,
      row: { duration_sec: '60', initial_verdict: null },
    });
    rpc.mockResolvedValue({ data: [{ status: 'submitted' }], error: null });
  });

  it('is dynamic Node, no-store, validates actual duration, and returns exact status', async () => {
    expect(runtime).toBe('nodejs');
    expect(dynamic).toBe('force-dynamic');
    const response = await POST(request(present), { params: { itemId: ITEM } });
    expect(response.status).toBe(200);
    expect(response.headers.get('cache-control')).toContain('no-store');
    expect(await response.json()).toEqual({ status: 'submitted' });
    expect(rpc).toHaveBeenCalledWith('fn_submit_gme_negative_audit', {
      p_item_id: ITEM,
      p_reviewer_id: 'bearer-reviewer',
      p_verdict: 'gecko_present',
      p_representative_sec: 4.2,
      p_bbox: { x: 0.1, y: 0.2, width: 0.3, height: 0.4 },
    });
  });

  it('rejects values past the actual DB duration before submit RPC', async () => {
    requireAuditAssignment.mockResolvedValue({
      ok: true,
      row: { duration_sec: '4', initial_verdict: null },
    });
    const response = await POST(request(present), { params: { itemId: ITEM } });
    expect(response.status).toBe(400);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('rejects forged identity/internal fields and query fields', async () => {
    const forgedBody = await POST(request({ ...present, reviewer_id: 'other' }), {
      params: { itemId: ITEM },
    });
    expect(forgedBody.status).toBe(400);
    expect(requireAuditAssignment).not.toHaveBeenCalled();
    expect(rpc).not.toHaveBeenCalled();

    requireAuditAssignment.mockClear();
    const forgedQuery = await POST(request(present, '?reviewer_id=other'), {
      params: { itemId: ITEM },
    });
    expect(forgedQuery.status).toBe(400);
    expect(requireAuditAssignment).not.toHaveBeenCalled();
  });

  it('keeps invalid-body ordering independent of whether the item is assigned', async () => {
    requireAuditAssignment.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: '대상을 찾을 수 없어.', code: 'not_assigned' }, { status: 404 }),
    });
    const response = await POST(request({ ...present, internal: true }), {
      params: { itemId: ITEM },
    });
    expect(response.status).toBe(400);
    expect(requireAuditAssignment).not.toHaveBeenCalled();
  });

  it('returns wrong reviewer as 404 with zero submit calls', async () => {
    requireAuditAssignment.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: '대상을 찾을 수 없어.', code: 'not_assigned' }, { status: 404 }),
    });
    const response = await POST(request(present), { params: { itemId: ITEM } });
    expect(response.status).toBe(404);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('rejects malformed and oversized JSON with stable 400/413', async () => {
    const malformed = new NextRequest(
      `https://label.tera-ai.uk/api/labeling-v3/gme-audit/${ITEM}/submit`,
      { method: 'POST', body: '{', headers: { 'content-type': 'application/json' } },
    );
    expect((await POST(malformed, { params: { itemId: ITEM } })).status).toBe(400);

    const oversized = new NextRequest(
      `https://label.tera-ai.uk/api/labeling-v3/gme-audit/${ITEM}/submit`,
      {
        method: 'POST',
        body: `{"x":"${'x'.repeat(17 * 1024)}"}`,
        headers: { 'content-type': 'application/json' },
      },
    );
    expect((await POST(oversized, { params: { itemId: ITEM } })).status).toBe(413);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('rejects non-JSON MIME before assignment or write RPC', async () => {
    const invalidMime = new NextRequest(
      `https://label.tera-ai.uk/api/labeling-v3/gme-audit/${ITEM}/submit`,
      {
        method: 'POST',
        body: JSON.stringify(present),
        headers: { 'content-type': 'text/plain' },
      },
    );
    const response = await POST(invalidMime, { params: { itemId: ITEM } });
    expect(response.status).toBe(400);
    expect(requireAuditAssignment).not.toHaveBeenCalled();
    expect(rpc).not.toHaveBeenCalled();
  });

  it('auth failure calls no body-dependent assignment or write RPC', async () => {
    requireProductionLabelingAccess.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: 'unauthorized' }, { status: 401 }),
    });
    const response = await POST(request(present), { params: { itemId: ITEM } });
    expect(response.status).toBe(401);
    expect(requireAuditAssignment).not.toHaveBeenCalled();
    expect(rpc).not.toHaveBeenCalled();
  });

  it('maps duplicate to stable 409 without raw DB text', async () => {
    rpc.mockResolvedValue({ data: null, error: { code: 'PT410', message: 'raw duplicate detail' } });
    const response = await POST(request(present), { params: { itemId: ITEM } });
    expect(response.status).toBe(409);
    const body = await response.json();
    expect(body.code).toBe('already_submitted');
    expect(JSON.stringify(body)).not.toContain('raw');
  });
});
