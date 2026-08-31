import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { loadBlindSlotAccess, loadCurrentGmeOverlayStatus, fetchAndParseGmeOverlay, presignGet } = vi.hoisted(() => ({
  loadBlindSlotAccess: vi.fn(),
  loadCurrentGmeOverlayStatus: vi.fn(),
  fetchAndParseGmeOverlay: vi.fn(),
  presignGet: vi.fn(),
}));
vi.mock('../../_access', () => ({ loadBlindSlotAccess }));
vi.mock('@/lib/gmeOverlayServer', () => ({ loadCurrentGmeOverlayStatus, fetchAndParseGmeOverlay }));
vi.mock('@/lib/r2', () => ({ presignGet }));

import { GET } from './route';

const CLIP = '11111111-1111-4111-8111-111111111111';
const REVISION = 'b'.repeat(64);

function req() {
  return new NextRequest(`https://label.tera-ai.uk/api/labeling-v3/blind/${CLIP}/gme-overlay`);
}

describe('GET blind GME overlay', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    loadBlindSlotAccess.mockResolvedValue({
      ok: true,
      userId: 'reviewer-1',
      scope: { cohortKind: 'live', cohortId: null },
      clip: { id: CLIP, duration_sec: 60 },
    });
    loadCurrentGmeOverlayStatus.mockResolvedValue({
      state: 'ready',
      source: {
        runId: 'private-run-id', overlayRevision: REVISION,
        artifactKey: 'terra-derived/gme/v1/permanent/private.json.gz', artifactBytes: 100,
      },
    });
    presignGet.mockResolvedValue('https://r2.example/signed');
    fetchAndParseGmeOverlay.mockResolvedValue({
      duration_sec: 60,
      points: [{ track_index: 0, timestamp_sec: 1, bbox_norm: [0.1, 0.2, 0.3, 0.4], confidence: 0.9, provenance: 'observed' }],
    });
  });

  it('slot 인가 후 익명 bbox와 revision만 반환한다', async () => {
    const response = await GET(req(), { params: { clipId: CLIP } });
    expect(response.status).toBe(200);
    const body = await response.json();
    expect(body).toMatchObject({
      state: 'ready', available: true, model_version: 'v2.6',
      overlay_revision: REVISION, duration_sec: 60,
    });
    expect(JSON.stringify(body)).not.toContain('private-run-id');
    expect(JSON.stringify(body)).not.toContain('permanent/');
    expect(presignGet).toHaveBeenCalledWith(
      'terra-derived/gme/v1/permanent/private.json.gz',
      300,
      { responseContentEncoding: 'identity' },
    );
  });

  it('GME run이 없으면 라벨링을 막지 않는 unavailable 응답을 준다', async () => {
    loadCurrentGmeOverlayStatus.mockResolvedValue({ state: 'pending' });
    const response = await GET(req(), { params: { clipId: CLIP } });
    expect(await response.json()).toEqual({
      state: 'pending', available: false, model_version: 'v2.6',
      overlay_revision: null, duration_sec: 60, points: [],
    });
    expect(presignGet).not.toHaveBeenCalled();
  });

  it('artifact integrity 오류도 비밀 원문 없이 unavailable로 접는다', async () => {
    fetchAndParseGmeOverlay.mockRejectedValue(new Error('private R2 key and credential'));
    const response = await GET(req(), { params: { clipId: CLIP } });
    expect(response.status).toBe(200);
    expect(await response.json()).toMatchObject({
      state: 'unavailable', available: false, model_version: 'v2.6', overlay_revision: null,
    });
  });

  it('slot 미인가면 artifact 조회를 시작하지 않는다', async () => {
    loadBlindSlotAccess.mockResolvedValue({ ok: false, response: NextResponse.json({ code: 'not_assigned' }, { status: 404 }) });
    const response = await GET(req(), { params: { clipId: CLIP } });
    expect(response.status).toBe(404);
    expect(loadCurrentGmeOverlayStatus).not.toHaveBeenCalled();
  });
});
