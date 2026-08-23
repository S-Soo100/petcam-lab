import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { requireProductionLabelingAccess, loadAuditMediaKey, presignGet } = vi.hoisted(() => ({
  requireProductionLabelingAccess: vi.fn(),
  loadAuditMediaKey: vi.fn(),
  presignGet: vi.fn(),
}));
vi.mock('@/lib/labelingAccess', () => ({ requireProductionLabelingAccess }));
vi.mock('@/lib/gmeNegativeAuditServer', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/gmeNegativeAuditServer')>()),
  loadAuditMediaKey,
}));
vi.mock('@/lib/r2', () => ({ presignGet }));

import { dynamic, GET, runtime } from './route';

const ITEM = '11111111-1111-4111-8111-111111111111';
function request(query = '') {
  return new NextRequest(
    `https://label.tera-ai.uk/api/labeling-v3/gme-audit/${ITEM}/file/url${query}`,
  );
}

describe('GET /api/labeling-v3/gme-audit/[itemId]/file/url', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireProductionLabelingAccess.mockResolvedValue({
      ok: true,
      userId: 'bearer-reviewer',
      isOwner: false,
    });
    loadAuditMediaKey.mockResolvedValue({ ok: true, r2Key: 'private/source.mp4' });
    presignGet.mockResolvedValue('https://r2.example/short-signed');
  });

  it('is dynamic Node, signs only after assignment, and returns url plus short expiry', async () => {
    expect(runtime).toBe('nodejs');
    expect(dynamic).toBe('force-dynamic');
    const response = await GET(request(), { params: { itemId: ITEM } });
    expect(response.status).toBe(200);
    expect(response.headers.get('cache-control')).toContain('no-store');
    expect(await response.json()).toEqual({
      url: 'https://r2.example/short-signed',
      expires_in: 300,
    });
    expect(loadAuditMediaKey).toHaveBeenCalledWith('bearer-reviewer', ITEM);
    expect(presignGet).toHaveBeenCalledWith('private/source.mp4', 300);
    expect(loadAuditMediaKey.mock.invocationCallOrder[0]).toBeLessThan(
      presignGet.mock.invocationCallOrder[0],
    );
  });

  it('wrong assignment returns stable 404 with zero signer calls', async () => {
    loadAuditMediaKey.mockResolvedValue({
      ok: false,
      response: NextResponse.json(
        { detail: '대상을 찾을 수 없어.', code: 'not_assigned' },
        { status: 404 },
      ),
    });
    const response = await GET(request(), { params: { itemId: ITEM } });
    expect(response.status).toBe(404);
    expect(presignGet).not.toHaveBeenCalled();
  });

  it('rejects every query field before assignment or signing', async () => {
    const response = await GET(request('?reviewer_id=other'), { params: { itemId: ITEM } });
    expect(response.status).toBe(400);
    expect(loadAuditMediaKey).not.toHaveBeenCalled();
    expect(presignGet).not.toHaveBeenCalled();
  });

  it('maps signer failure to safe 502 without key or raw error', async () => {
    presignGet.mockRejectedValue(new Error('credential failed for private/source.mp4'));
    const response = await GET(request(), { params: { itemId: ITEM } });
    expect(response.status).toBe(502);
    const json = JSON.stringify(await response.json());
    expect(json).not.toContain('private/source.mp4');
    expect(json).not.toContain('credential');
  });
});
