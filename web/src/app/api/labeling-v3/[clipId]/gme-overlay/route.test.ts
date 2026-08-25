import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { loadMotionClipAccess, loadCurrentGmeOverlaySource, fetchAndParseGmeOverlay, presignGet } = vi.hoisted(() => ({
  loadMotionClipAccess: vi.fn(),
  loadCurrentGmeOverlaySource: vi.fn(),
  fetchAndParseGmeOverlay: vi.fn(),
  presignGet: vi.fn(),
}));
vi.mock('../../_access', () => ({ loadMotionClipAccess }));
vi.mock('@/lib/gmeOverlayServer', () => ({ loadCurrentGmeOverlaySource, fetchAndParseGmeOverlay }));
vi.mock('@/lib/r2', () => ({ presignGet }));

import { GET } from './route';

const CLIP = '11111111-1111-4111-8111-111111111111';
const REVISION = 'b'.repeat(64);
const req = () => new NextRequest(`https://label.tera-ai.uk/api/labeling-v3/${CLIP}/gme-overlay`);

describe('GET owner GME overlay', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    loadMotionClipAccess.mockResolvedValue({ ok: true, userId: 'owner', clip: { id: CLIP, duration_sec: 60 } });
    loadCurrentGmeOverlaySource.mockResolvedValue({
      runId: 'private-run', overlayRevision: REVISION, artifactKey: 'private.json.gz', artifactBytes: 100,
    });
    presignGet.mockResolvedValue('https://signed.invalid');
    fetchAndParseGmeOverlay.mockResolvedValue({ duration_sec: 60, points: [] });
  });

  it('Owner 인가 후 compressed artifact를 검증해 익명 overlay만 반환한다', async () => {
    const response = await GET(req(), { params: { clipId: CLIP } });
    expect(response.status).toBe(200);
    expect(await response.json()).toMatchObject({ available: true, overlay_revision: REVISION });
    expect(presignGet).toHaveBeenCalledWith('private.json.gz', 300, { responseContentEncoding: 'identity' });
  });

  it('Owner 미인가면 artifact를 읽지 않는다', async () => {
    loadMotionClipAccess.mockResolvedValue({ ok: false, response: NextResponse.json({}, { status: 403 }) });
    expect((await GET(req(), { params: { clipId: CLIP } })).status).toBe(403);
    expect(loadCurrentGmeOverlaySource).not.toHaveBeenCalled();
  });
});
