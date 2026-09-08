import { NextRequest } from 'next/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { loadV4ClipAccess, rpc } = vi.hoisted(() => ({ loadV4ClipAccess: vi.fn(), rpc: vi.fn() }));
vi.mock('../../../_access', () => ({ loadV4ClipAccess }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));
vi.mock('../../../_claims', () => ({ NEXT_CANDIDATES: 6, pickUnclaimed: async (ids: string[]) => ids[0] ?? null }));
vi.mock('@/lib/labelingV3Server', () => ({
  readGmeActiveContract: () => ({ engine_schema_version: 'gme-shadow-v1', algorithm_version: 'gme-motion-v1', detector_identity: 'a'.repeat(64) }),
}));

import { GET } from './route';

const CLIP = '00000000-0000-4000-8000-000000000005';
const NEXT = '00000000-0000-4000-8000-000000000004';
const CAM = '40000000-0000-4000-8000-000000000001';
const req = () => new NextRequest(`https://label.tera-ai.uk/api/labeling-v4/clips/${CLIP}/next`);
const clip = { id: CLIP, camera_id: CAM, started_at: '2026-09-08T05:00:00Z', duration_sec: 60, r2_key: 'terra-clips/clips/x.mp4', clip_purpose: 'production' };

beforeEach(() => {
  vi.clearAllMocks();
  loadV4ClipAccess.mockResolvedValue({ ok: true, userId: 'u1', isOwner: false, clip });
  rpc.mockResolvedValue({ data: [{ clip_id: NEXT }], error: null });
});

describe('GET /api/labeling-v4/clips/[clipId]/next', () => {
  it('cursor 는 현재 clip 의 (started_at, id), 같은 카메라·unlabeled·후보 6개(보는 중 건너뛰기)', async () => {
    const body = await (await GET(req(), { params: { clipId: CLIP } })).json();
    expect(body).toEqual({ next_clip_id: NEXT });
    expect(rpc).toHaveBeenCalledWith('fn_list_labeling_v4_clips', {
      p_viewer_id: 'u1', p_is_owner: false, p_scope: 'all', p_camera_ids: [CAM],
      p_label_state: 'unlabeled', p_highlight_state: null, p_behavior_flag: null,
      p_engine_schema_version: 'gme-shadow-v1', p_algorithm_version: 'gme-motion-v1', p_detector_identity: 'a'.repeat(64),
      p_cursor_started_at: clip.started_at, p_cursor_id: CLIP, p_limit: 6,
    });
  });
  it('?sample= 은 RPC 에 p_sample_id 로, 잘못된 형식은 400', async () => {
    await GET(new NextRequest(`https://label.tera-ai.uk/api/labeling-v4/clips/${CLIP}/next?sample=eval-2026-09`), { params: { clipId: CLIP } });
    expect(rpc.mock.calls[0][1]).toMatchObject({ p_sample_id: 'eval-2026-09' });
    expect((await GET(new NextRequest(`https://label.tera-ai.uk/api/labeling-v4/clips/${CLIP}/next?sample=BAD%20id`), { params: { clipId: CLIP } })).status).toBe(400);
  });
  it('다음이 없으면 next_clip_id null', async () => {
    rpc.mockResolvedValue({ data: [], error: null });
    expect(await (await GET(req(), { params: { clipId: CLIP } })).json()).toEqual({ next_clip_id: null });
  });
  it('카메라 없는 clip 은 카메라 필터 없이(null)', async () => {
    loadV4ClipAccess.mockResolvedValue({ ok: true, userId: 'u1', isOwner: false, clip: { ...clip, camera_id: null } });
    await GET(req(), { params: { clipId: CLIP } });
    expect(rpc.mock.calls[0][1]).toMatchObject({ p_camera_ids: null });
  });
  it('접근 가드 실패는 그대로, RPC 호출 없음', async () => {
    loadV4ClipAccess.mockResolvedValue({ ok: false, response: new Response(null, { status: 404 }) });
    expect((await GET(req(), { params: { clipId: CLIP } })).status).toBe(404);
    expect(rpc).not.toHaveBeenCalled();
  });
});
