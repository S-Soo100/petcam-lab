import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { loadBlindSlotAccess, loadCurrentGmeOverlaySource, rpc, randomUUID } = vi.hoisted(() => ({
  loadBlindSlotAccess: vi.fn(),
  loadCurrentGmeOverlaySource: vi.fn(),
  rpc: vi.fn(),
  randomUUID: vi.fn(() => '90000000-0000-4000-8000-000000000001'),
}));
vi.mock('../../_access', () => ({ loadBlindSlotAccess }));
vi.mock('@/lib/gmeOverlayServer', () => ({ loadCurrentGmeOverlaySource }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));
vi.mock('node:crypto', async (importOriginal) => ({ ...(await importOriginal<typeof import('node:crypto')>()), randomUUID }));

import { POST } from './route';

const CLIP = '11111111-1111-4111-8111-111111111111';
const RUN = '22222222-2222-4222-8222-222222222222';
const REVISION = 'b'.repeat(64);

function req(body: unknown) {
  return new NextRequest(`https://label.tera-ai.uk/api/labeling-v3/blind/${CLIP}/gme-feedback`, {
    method: 'POST', body: JSON.stringify(body), headers: { 'content-type': 'application/json' },
  });
}

describe('POST blind GME feedback', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    loadBlindSlotAccess.mockResolvedValue({
      ok: true, userId: 'reviewer-1',
      scope: { cohortKind: 'live', cohortId: null },
      clip: { id: CLIP, duration_sec: 60 },
    });
    loadCurrentGmeOverlaySource.mockResolvedValue({
      runId: RUN, overlayRevision: REVISION,
      artifactKey: 'private.json.gz', artifactBytes: 100,
    });
    rpc.mockResolvedValue({ data: [{ event_id: 'event', timestamp_sec: 12.346, status: 'recorded' }], error: null });
  });

  it.each(['miss', 'false_positive'] as const)('%s를 현재 run provenance와 blind surface로 기록한다', async (feedbackKind) => {
    const response = await POST(req({
      feedback_kind: feedbackKind, timestamp_sec: 12.3456, overlay_revision: REVISION,
    }), { params: { clipId: CLIP } });
    expect(response.status).toBe(200);
    expect(rpc).toHaveBeenCalledWith('fn_append_motion_clip_gme_feedback', {
      p_event_id: '90000000-0000-4000-8000-000000000001',
      p_clip_id: CLIP,
      p_reviewer_id: 'reviewer-1',
      p_feedback_kind: feedbackKind,
      p_surface: 'blind_live',
      p_cohort_id: null,
      p_gme_run_id: RUN,
      p_overlay_revision: REVISION,
      p_timestamp_sec: 12.346,
    });
  });

  it('알 수 없는 feedback kind와 slot 미인가는 artifact 조회 전에 닫는다', async () => {
    expect((await POST(req({ feedback_kind: 'other', timestamp_sec: 1, overlay_revision: REVISION }), { params: { clipId: CLIP } })).status).toBe(400);
    loadBlindSlotAccess.mockResolvedValue({ ok: false, response: NextResponse.json({}, { status: 404 }) });
    expect((await POST(req({ feedback_kind: 'miss', timestamp_sec: 1, overlay_revision: REVISION }), { params: { clipId: CLIP } })).status).toBe(404);
    expect(loadCurrentGmeOverlaySource).not.toHaveBeenCalled();
  });
});
