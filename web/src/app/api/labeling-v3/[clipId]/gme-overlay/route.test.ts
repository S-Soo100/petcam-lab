import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { loadMotionClipAccess, loadCurrentGmeOverlaySource, fetchAndParseGmeOverlay, presignGet, readGmeActiveContract } = vi.hoisted(() => ({
  loadMotionClipAccess: vi.fn(),
  loadCurrentGmeOverlaySource: vi.fn(),
  fetchAndParseGmeOverlay: vi.fn(),
  presignGet: vi.fn(),
  readGmeActiveContract: vi.fn(),
}));
vi.mock('../../_access', () => ({ loadMotionClipAccess }));
vi.mock('@/lib/gmeOverlayServer', () => ({ loadCurrentGmeOverlaySource, fetchAndParseGmeOverlay }));
vi.mock('@/lib/r2', () => ({ presignGet }));
vi.mock('@/lib/labelingV3Server', () => ({ readGmeActiveContract }));

import { GET } from './route';

const CLIP = '11111111-1111-4111-8111-111111111111';
const REVISION = 'b'.repeat(64);
const IDENTITY = 'a'.repeat(64);
const req = () => new NextRequest(`https://label.tera-ai.uk/api/labeling-v3/${CLIP}/gme-overlay`);

describe('GET owner GME overlay', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    loadMotionClipAccess.mockResolvedValue({ ok: true, userId: 'owner', clip: { id: CLIP, duration_sec: 60 } });
    loadCurrentGmeOverlaySource.mockResolvedValue({
      runId: 'private-run', overlayRevision: REVISION, artifactKey: 'private.json.gz', artifactBytes: 100,
    });
    presignGet.mockResolvedValue('https://signed.invalid');
    readGmeActiveContract.mockReturnValue({
      engine_schema_version: 'gme-shadow-v1', algorithm_version: 'gme-motion-v1', detector_identity: IDENTITY,
    });
    fetchAndParseGmeOverlay.mockResolvedValue({ duration_sec: 60, points: [], intervals: [] });
  });

  it('Owner 인가 후 compressed artifact를 검증해 익명 overlay만 반환한다', async () => {
    const response = await GET(req(), { params: { clipId: CLIP } });
    expect(response.status).toBe(200);
    expect(await response.json()).toMatchObject({ available: true, overlay_revision: REVISION, intervals: [] });
    expect(loadCurrentGmeOverlaySource).toHaveBeenCalledWith(CLIP, IDENTITY, 'gme-motion-v1');
    expect(presignGet).toHaveBeenCalledWith('private.json.gz', 300, { responseContentEncoding: 'identity' });
  });

  it('현재 identity 결과가 없으면 고정 형태의 unavailable을 반환한다', async () => {
    loadCurrentGmeOverlaySource.mockResolvedValue(null);
    const response = await GET(req(), { params: { clipId: CLIP } });
    expect(await response.json()).toEqual({
      available: false,
      overlay_revision: null,
      duration_sec: 60,
      points: [],
      intervals: [],
    });
  });

  it('Owner 미인가면 artifact를 읽지 않는다', async () => {
    loadMotionClipAccess.mockResolvedValue({ ok: false, response: NextResponse.json({}, { status: 403 }) });
    expect((await GET(req(), { params: { clipId: CLIP } })).status).toBe(403);
    expect(loadCurrentGmeOverlaySource).not.toHaveBeenCalled();
  });
});
