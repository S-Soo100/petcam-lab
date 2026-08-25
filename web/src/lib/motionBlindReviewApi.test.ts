import { beforeEach, describe, expect, it, vi } from 'vitest';

const { getSession } = vi.hoisted(() => ({ getSession: vi.fn() }));
vi.mock('./supabaseBrowser', () => ({
  getSupabaseBrowser: () => ({ auth: { getSession } }),
}));

import {
  getBlindGmeOverlay,
  getOwnerConflictDetail,
  getOwnerConflictFileUrl,
  getOwnerConflicts,
  reportBlindGmeMiss,
  resolveOwnerConflict,
} from './motionBlindReviewApi';

const CLIP = '11111111-1111-4111-8111-111111111111';
const COHORT = '22222222-2222-4222-8222-222222222222';

describe('owner conflict browser API cohort scope', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    getSession.mockResolvedValue({ data: { session: null } });
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation(() =>
        Promise.resolve(
          new Response(JSON.stringify({ items: [], next_cursor: null, has_more: false }), {
            status: 200,
            headers: { 'content-type': 'application/json' },
          }),
        ),
      ),
    );
  });

  it('keeps the selected canary cohort on list and detail reads', async () => {
    await getOwnerConflicts(null, COHORT);
    await getOwnerConflictDetail(CLIP, COHORT);
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe(
      `/api/labeling-v3/blind/owner/conflicts?cohort_id=${COHORT}`,
    );
    expect(vi.mocked(fetch).mock.calls[1][0]).toBe(
      `/api/labeling-v3/blind/owner/${CLIP}?cohort_id=${COHORT}`,
    );
  });

  it('keeps canary scope on resolve without moving expected_updated_at out of the body', async () => {
    await resolveOwnerConflict({
      clipId: CLIP,
      cohortId: COHORT,
      choice: 'a',
      expectedUpdatedAt: '2026-07-22T00:00:00Z',
    });
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe(
      `/api/labeling-v3/blind/owner/${CLIP}/resolve?cohort_id=${COHORT}`,
    );
    expect(JSON.parse(String(init?.body))).toMatchObject({
      choice: 'a',
      expected_updated_at: '2026-07-22T00:00:00Z',
    });
  });

  it('uses the dedicated owner media endpoint with the selected canary scope', async () => {
    await getOwnerConflictFileUrl(CLIP, COHORT);
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe(
      `/api/labeling-v3/blind/owner/${CLIP}/file/url?cohort_id=${COHORT}`,
    );
  });

  it('preserves the live default URLs when cohort scope is absent', async () => {
    await getOwnerConflicts(null);
    await getOwnerConflictDetail(CLIP);
    await getOwnerConflictFileUrl(CLIP);
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe(
      '/api/labeling-v3/blind/owner/conflicts',
    );
    expect(vi.mocked(fetch).mock.calls[1][0]).toBe(
      `/api/labeling-v3/blind/owner/${CLIP}`,
    );
    expect(vi.mocked(fetch).mock.calls[2][0]).toBe(
      `/api/labeling-v3/blind/owner/${CLIP}/file/url`,
    );
  });
});

describe('blind GME overlay browser API', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    getSession.mockResolvedValue({ data: { session: null } });
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify({
          available: true,
          overlay_revision: 'b'.repeat(64),
          duration_sec: 60,
          points: [],
          status: 'recorded',
          timestamp_sec: 1.234,
        }), { status: 200, headers: { 'content-type': 'application/json' } }))),
    );
  });

  it('canary scope를 overlay GET과 miss POST에 유지한다', async () => {
    await getBlindGmeOverlay(CLIP, COHORT);
    await reportBlindGmeMiss({
      clipId: CLIP,
      cohortId: COHORT,
      timestampSec: 1.234,
      overlayRevision: 'b'.repeat(64),
    });

    const calls = vi.mocked(fetch).mock.calls;
    expect(calls[0][0]).toBe(`/api/labeling-v3/blind/${CLIP}/gme-overlay?cohort_id=${COHORT}`);
    expect(calls[1][0]).toBe(`/api/labeling-v3/blind/${CLIP}/gme-miss?cohort_id=${COHORT}`);
    expect(JSON.parse(String(calls[1][1]?.body))).toEqual({
      timestamp_sec: 1.234,
      overlay_revision: 'b'.repeat(64),
    });
  });
});
