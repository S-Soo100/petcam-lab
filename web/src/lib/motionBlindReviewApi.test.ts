import { beforeEach, describe, expect, it, vi } from 'vitest';

const { getSession } = vi.hoisted(() => ({ getSession: vi.fn() }));
vi.mock('./supabaseBrowser', () => ({
  getSupabaseBrowser: () => ({ auth: { getSession } }),
}));

import {
  getOwnerConflictDetail,
  getOwnerConflicts,
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

  it('preserves the live default URLs when cohort scope is absent', async () => {
    await getOwnerConflicts(null);
    await getOwnerConflictDetail(CLIP);
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe(
      '/api/labeling-v3/blind/owner/conflicts',
    );
    expect(vi.mocked(fetch).mock.calls[1][0]).toBe(
      `/api/labeling-v3/blind/owner/${CLIP}`,
    );
  });
});
