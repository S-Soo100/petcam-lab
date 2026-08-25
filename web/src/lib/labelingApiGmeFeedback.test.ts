import { beforeEach, describe, expect, it, vi } from 'vitest';

const { getSession } = vi.hoisted(() => ({ getSession: vi.fn() }));
vi.mock('./supabaseBrowser', () => ({
  getSupabaseBrowser: () => ({ auth: { getSession } }),
}));

import { getOwnerGmeOverlay, reportOwnerGmeFeedback } from './labelingV3Api';

const CLIP = '11111111-1111-4111-8111-111111111111';

describe('Owner direct-label GME browser API', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    getSession.mockResolvedValue({ data: { session: null } });
    vi.stubGlobal('fetch', vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify({
      available: true,
      overlay_revision: 'b'.repeat(64),
      duration_sec: 60,
      points: [],
      status: 'recorded',
      timestamp_sec: 3.21,
    }), { status: 200, headers: { 'content-type': 'application/json' } }))));
  });

  it('Owner 전용 overlay와 feedback same-origin endpoint를 사용한다', async () => {
    await getOwnerGmeOverlay(CLIP);
    await reportOwnerGmeFeedback({
      clipId: CLIP,
      feedbackKind: 'miss',
      timestampSec: 3.21,
      overlayRevision: 'b'.repeat(64),
    });

    const calls = vi.mocked(fetch).mock.calls;
    expect(calls[0][0]).toBe(`/api/labeling-v3/${CLIP}/gme-overlay`);
    expect(calls[1][0]).toBe(`/api/labeling-v3/${CLIP}/gme-feedback`);
    expect(JSON.parse(String(calls[1][1]?.body))).toEqual({
      feedback_kind: 'miss',
      timestamp_sec: 3.21,
      overlay_revision: 'b'.repeat(64),
    });
  });
});
