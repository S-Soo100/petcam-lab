import { afterAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

const { requireProductionLabelingAccess, rpc } = vi.hoisted(() => ({
  requireProductionLabelingAccess: vi.fn(),
  rpc: vi.fn(),
}));
vi.mock('@/lib/labelingAccess', () => ({ requireProductionLabelingAccess }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));

import { GET } from './route';

const CLIP = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const PREV_ENV = process.env.DEV_USER_ID;
const PREV_CANONICAL_ENV = process.env.LABELING_CANONICAL_GT_LIBRARY_READ_ENABLED;

function req() {
  return new NextRequest(`https://label.tera-ai.uk/api/labeling-v3/library/${CLIP}`);
}

describe('GET /api/labeling-v3/library/[clipId]', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    process.env.DEV_USER_ID = 'owner-uuid';
    delete process.env.LABELING_CANONICAL_GT_LIBRARY_READ_ENABLED;
    requireProductionLabelingAccess.mockResolvedValue({ ok: true, userId: 'labeler-1', isOwner: false });
    rpc.mockResolvedValue({
      data: [
        {
          clip_id: CLIP,
          camera_id: null,
          camera_name: '카메라',
          started_at: '2026-07-22T10:00:00Z',
          duration_sec: 30,
          label_state: 'final',
          label_source: 'owner_legacy',
          final_decision: 'label',
          final_gt: { behavior: 'moving' },
        },
      ],
      error: null,
    });
  });
  afterAll(() => {
    process.env.DEV_USER_ID = PREV_ENV;
    if (PREV_CANONICAL_ENV === undefined) {
      delete process.env.LABELING_CANONICAL_GT_LIBRARY_READ_ENABLED;
    } else {
      process.env.LABELING_CANONICAL_GT_LIBRARY_READ_ENABLED = PREV_CANONICAL_ENV;
    }
  });

  it('잘못된 UUID 는 400', async () => {
    const res = await GET(new NextRequest('https://label.tera-ai.uk/api/labeling-v3/library/nope'), {
      params: { clipId: 'nope' },
    });
    expect(res.status).toBe(400);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('같은 read RPC 를 p_clip_id 로 좁혀 호출한다', async () => {
    await GET(req(), { params: { clipId: CLIP } });
    const args = rpc.mock.calls[0][1];
    expect(args.p_clip_id).toBe(CLIP);
    expect(args.p_limit).toBe(1);
  });

  it('독립 flag가 켜지면 canonical 단건 RPC provenance를 공개한다', async () => {
    process.env.LABELING_CANONICAL_GT_LIBRARY_READ_ENABLED = 'true';
    rpc.mockResolvedValue({
      data: [{
        clip_id: CLIP,
        camera_id: null,
        camera_name: '카메라',
        started_at: '2026-07-22T10:00:00Z',
        duration_sec: 30,
        label_state: 'final',
        label_source: 'blind_consensus',
        final_decision: 'label',
        final_gt: { primary_action: 'moving' },
        gt_revision_id: 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee',
        gt_source_type: 'blind_consensus',
        gt_updated_at: '2026-08-04T00:00:00Z',
      }],
      error: null,
    });
    const body = await (await GET(req(), { params: { clipId: CLIP } })).json();
    expect(rpc).toHaveBeenCalledWith(
      'fn_list_motion_labeling_library_canonical',
      expect.any(Object),
    );
    expect(body.gt_revision_id).toBe('eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee');
  });

  it('행 있으면 단건 아이템 반환', async () => {
    const res = await GET(req(), { params: { clipId: CLIP } });
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.clip_id).toBe(CLIP);
    expect(body.label_source).toBe('owner_legacy');
  });

  it('행 없으면 404', async () => {
    rpc.mockResolvedValue({ data: [], error: null });
    const res = await GET(req(), { params: { clipId: CLIP } });
    expect(res.status).toBe(404);
  });
});
