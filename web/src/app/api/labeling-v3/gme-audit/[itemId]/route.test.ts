import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { requireProductionLabelingAccess, loadAuditDetail } = vi.hoisted(() => ({
  requireProductionLabelingAccess: vi.fn(),
  loadAuditDetail: vi.fn(),
}));
vi.mock('@/lib/labelingAccess', () => ({ requireProductionLabelingAccess }));
vi.mock('@/lib/gmeNegativeAuditServer', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/gmeNegativeAuditServer')>()),
  loadAuditDetail,
}));

import { dynamic, GET, runtime } from './route';

const ITEM = '11111111-1111-4111-8111-111111111111';
function request(query = '') {
  return new NextRequest(`https://label.tera-ai.uk/api/labeling-v3/gme-audit/${ITEM}${query}`);
}

const ownItem = {
  item_id: ITEM,
  ordinal: 1,
  captured_at: '2026-08-23T10:00:00Z',
  duration_sec: 60,
  media_ready: true,
  initial_verdict: 'gecko_absent',
  initial_representative_sec: null,
  initial_bbox: null,
  effective_verdict: 'gecko_present',
  effective_representative_sec: 4.2,
  effective_bbox: { x: 0.1, y: 0.2, width: 0.3, height: 0.4 },
  revision: 'own-opaque-revision',
};

describe('GET /api/labeling-v3/gme-audit/[itemId]', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireProductionLabelingAccess.mockResolvedValue({
      ok: true,
      userId: 'bearer-reviewer',
      isOwner: false,
    });
    loadAuditDetail.mockResolvedValue({ ok: true, item: ownItem });
  });

  it('is dynamic Node, no-store, and returns own opaque revision', async () => {
    expect(runtime).toBe('nodejs');
    expect(dynamic).toBe('force-dynamic');
    const response = await GET(request(), { params: { itemId: ITEM } });
    expect(response.status).toBe(200);
    expect(response.headers.get('cache-control')).toContain('no-store');
    expect(await response.json()).toEqual(ownItem);
    expect(loadAuditDetail).toHaveBeenCalledWith('bearer-reviewer', ITEM);
  });

  it('rejects query identity and never exposes forbidden model/source fields', async () => {
    const forged = await GET(request('?reviewer_id=other'), { params: { itemId: ITEM } });
    expect(forged.status).toBe(400);
    expect(loadAuditDetail).not.toHaveBeenCalled();

    const response = await GET(request(), { params: { itemId: ITEM } });
    const json = JSON.stringify(await response.json());
    for (const forbidden of [
      'submission_digest',
      'expected_submission_digest',
      'hash',
      'stratum',
      'gme_',
      'control',
      'r2_key',
      'reviewer_id',
    ]) {
      expect(json).not.toContain(forbidden);
    }
  });

  it('returns stable 404 for another reviewer without leaking detail', async () => {
    loadAuditDetail.mockResolvedValue({
      ok: false,
      response: NextResponse.json(
        { detail: '대상을 찾을 수 없어.', code: 'not_assigned' },
        { status: 404 },
      ),
    });
    const response = await GET(request(), { params: { itemId: ITEM } });
    expect(response.status).toBe(404);
    expect(JSON.stringify(await response.json())).not.toContain('revision');
  });

  it('auth failure calls no assignment/detail loader', async () => {
    requireProductionLabelingAccess.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: 'unauthorized' }, { status: 401 }),
    });
    const response = await GET(request(), { params: { itemId: ITEM } });
    expect(response.status).toBe(401);
    expect(loadAuditDetail).not.toHaveBeenCalled();
  });
});
