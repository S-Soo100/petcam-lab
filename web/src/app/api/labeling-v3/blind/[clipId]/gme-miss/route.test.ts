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
  return new NextRequest(`https://label.tera-ai.uk/api/labeling-v3/blind/${CLIP}/gme-miss`, {
    method: 'POST', body: JSON.stringify(body), headers: { 'content-type': 'application/json' },
  });
}

describe('POST blind GME miss', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    loadBlindSlotAccess.mockResolvedValue({
      ok: true, userId: 'reviewer-1',
      scope: { cohortKind: 'live', cohortId: null },
      clip: { id: CLIP, duration_sec: 60 },
    });
    loadCurrentGmeOverlaySource.mockResolvedValue({
      runId: RUN, overlayRevision: REVISION,
      artifactKey: 'terra-derived/gme/v1/permanent/private.json.gz', artifactBytes: 100,
    });
    rpc.mockResolvedValue({ data: [{ event_id: 'event', timestamp_sec: 12.346, status: 'recorded' }], error: null });
  });

  it('body의 시각/revision만 받고 현재 run id는 서버에서 채운다', async () => {
    const response = await POST(req({ timestamp_sec: 12.3456, overlay_revision: REVISION }), { params: { clipId: CLIP } });
    expect(response.status).toBe(200);
    expect(rpc).toHaveBeenCalledWith('fn_append_motion_clip_gme_miss', {
      p_event_id: '90000000-0000-4000-8000-000000000001',
      p_clip_id: CLIP,
      p_reviewer_id: 'reviewer-1',
      p_cohort_kind: 'live',
      p_cohort_id: null,
      p_gme_run_id: RUN,
      p_overlay_revision: REVISION,
      p_timestamp_sec: 12.346,
    });
    expect(await response.json()).toMatchObject({ status: 'recorded', timestamp_sec: 12.346 });
  });

  it('현재 revision이 바뀌었으면 RPC 전에 409로 닫는다', async () => {
    const response = await POST(req({ timestamp_sec: 1, overlay_revision: 'c'.repeat(64) }), { params: { clipId: CLIP } });
    expect(response.status).toBe(409);
    expect((await response.json()).code).toBe('overlay_changed');
    expect(rpc).not.toHaveBeenCalled();
  });

  it('잘못된 timestamp는 400이고 slot 미인가면 current run을 읽지 않는다', async () => {
    expect((await POST(req({ timestamp_sec: 99, overlay_revision: REVISION }), { params: { clipId: CLIP } })).status).toBe(400);
    loadBlindSlotAccess.mockResolvedValue({ ok: false, response: NextResponse.json({}, { status: 404 }) });
    expect((await POST(req({ timestamp_sec: 1, overlay_revision: REVISION }), { params: { clipId: CLIP } })).status).toBe(404);
  });

  it('DB stale code를 409 generic 응답으로 보존한다', async () => {
    rpc.mockResolvedValue({ data: null, error: { code: 'PT409', message: 'secret db detail' } });
    const response = await POST(req({ timestamp_sec: 1, overlay_revision: REVISION }), { params: { clipId: CLIP } });
    expect(response.status).toBe(409);
    expect(JSON.stringify(await response.json())).not.toContain('secret');
  });
});
