import { NextRequest } from 'next/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { loadV4ClipAccess, loadHighlightDetail, isMotionMediaDeleted } = vi.hoisted(() => ({ loadV4ClipAccess: vi.fn(), loadHighlightDetail: vi.fn(), isMotionMediaDeleted: vi.fn() }));
vi.mock('../../_access', () => ({ loadV4ClipAccess }));
vi.mock('../../_highlight', () => ({ loadHighlightDetail }));
vi.mock('../../_behavior-flag', () => ({ loadBehaviorFlag: async () => ({ flagged: false, flagged_by_name: null, flagged_at: null }) }));
vi.mock('../../_featured', () => ({ loadFeaturedForClip: async () => null }));
vi.mock('@/lib/labelingV3Server', () => ({ isMotionMediaDeleted, motionLabelingDatabaseError: () => new Response(null, { status: 502 }) }));

import { GET } from './route';

const CLIP = '00000000-0000-4000-8000-000000000001';

beforeEach(() => {
  vi.clearAllMocks();
  loadV4ClipAccess.mockResolvedValue({ ok: true, userId: 'u1', isOwner: false, clip: { id: CLIP, camera_id: 'c1', started_at: '2026-09-08T00:00:00Z', duration_sec: 60, r2_key: 'k' } });
  isMotionMediaDeleted.mockResolvedValue(false);
  loadHighlightDetail.mockResolvedValue({ current: { source: 'rule', status: 'decided', value: true, rule_version: 'hl-rule-v0', reason: 'r', reviewer_name: null, decided_at: null, verdict_kind: null }, initial: { status: 'decided', value: true, rule_version: 'hl-rule-v0', reason: 'r', fired: ['long_activity'], shadow: [], features: null } });
});

describe('GET /api/labeling-v4/clips/[clipId]', () => {
  it('clip 메타 + highlight, r2_key 비노출', async () => {
    const body = await (await GET(new NextRequest(`https://label.tera-ai.uk/api/labeling-v4/clips/${CLIP}`), { params: { clipId: CLIP } })).json();
    expect(body).toEqual({ id: CLIP, camera_id: 'c1', started_at: '2026-09-08T00:00:00Z', duration_sec: 60, media_ready: true, highlight: expect.objectContaining({ current: expect.any(Object), initial: expect.any(Object) }), behavior_flag: { flagged: false, flagged_by_name: null, flagged_at: null }, featured: null });
    expect(JSON.stringify(body)).not.toContain('"k"');
  });
  it('media_deleted 면 media_ready=false', async () => {
    isMotionMediaDeleted.mockResolvedValue(true);
    const body = await (await GET(new NextRequest(`https://label.tera-ai.uk/api/labeling-v4/clips/${CLIP}`), { params: { clipId: CLIP } })).json();
    expect(body.media_ready).toBe(false);
  });
});
