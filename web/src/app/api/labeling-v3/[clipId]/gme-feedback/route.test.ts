import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { loadMotionClipAccess, loadCurrentGmeOverlaySource, rpc, randomUUID } = vi.hoisted(() => ({
  loadMotionClipAccess: vi.fn(),
  loadCurrentGmeOverlaySource: vi.fn(),
  rpc: vi.fn(),
  randomUUID: vi.fn(() => '90000000-0000-4000-8000-000000000001'),
}));
vi.mock('../../_access', () => ({ loadMotionClipAccess }));
vi.mock('@/lib/gmeOverlayServer', () => ({ loadCurrentGmeOverlaySource }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));
vi.mock('node:crypto', async (importOriginal) => ({ ...(await importOriginal<typeof import('node:crypto')>()), randomUUID }));

import { POST } from './route';

const CLIP = '11111111-1111-4111-8111-111111111111';
const RUN = '22222222-2222-4222-8222-222222222222';
const REVISION = 'b'.repeat(64);
function req(kind: string) {
  return new NextRequest(`https://label.tera-ai.uk/api/labeling-v3/${CLIP}/gme-feedback`, {
    method: 'POST',
    body: JSON.stringify({ feedback_kind: kind, timestamp_sec: 4.5678, overlay_revision: REVISION }),
    headers: { 'content-type': 'application/json' },
  });
}

describe('POST owner GME feedback', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    loadMotionClipAccess.mockResolvedValue({ ok: true, userId: 'owner', clip: { id: CLIP, duration_sec: 60 } });
    loadCurrentGmeOverlaySource.mockResolvedValue({ runId: RUN, overlayRevision: REVISION });
    rpc.mockResolvedValue({ data: [{ event_id: 'event', timestamp_sec: 4.568, status: 'recorded' }], error: null });
  });

  it('Owner bearer actor와 owner_direct surface로 오탐을 append한다', async () => {
    const response = await POST(req('false_positive'), { params: { clipId: CLIP } });
    expect(response.status).toBe(200);
    expect(rpc).toHaveBeenCalledWith('fn_append_motion_clip_gme_feedback', expect.objectContaining({
      p_reviewer_id: 'owner', p_feedback_kind: 'false_positive', p_surface: 'owner_direct',
      p_timestamp_sec: 4.568, p_gme_run_id: RUN,
    }));
  });

  it('Owner 미인가와 잘못된 kind는 write 전에 닫는다', async () => {
    loadMotionClipAccess.mockResolvedValue({ ok: false, response: NextResponse.json({}, { status: 403 }) });
    expect((await POST(req('miss'), { params: { clipId: CLIP } })).status).toBe(403);
    expect(rpc).not.toHaveBeenCalled();
    loadMotionClipAccess.mockResolvedValue({ ok: true, userId: 'owner', clip: { id: CLIP, duration_sec: 60 } });
    expect((await POST(req('other'), { params: { clipId: CLIP } })).status).toBe(400);
    expect(rpc).not.toHaveBeenCalled();
  });
});
