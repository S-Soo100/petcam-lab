import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { requireProductionLabelingAccess, from, presignGet } = vi.hoisted(() => ({
  requireProductionLabelingAccess: vi.fn(),
  from: vi.fn(),
  presignGet: vi.fn(),
}));
vi.mock('@/lib/labelingAccess', () => ({ requireProductionLabelingAccess }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { from } }));
vi.mock('@/lib/r2', () => ({ presignGet, SIGNED_URL_TTL_SEC: 300 }));

import { GET } from './route';

const CLIP = '11111111-1111-4111-8111-111111111111';

function builder(result: unknown) {
  const b: Record<string, unknown> = {};
  for (const m of ['select', 'eq', 'is', 'order', 'limit']) b[m] = () => b;
  b.then = (resolve: (v: unknown) => unknown) => Promise.resolve(result).then(resolve);
  return b;
}
function setTables(tables: Record<string, unknown>) {
  from.mockImplementation((t: string) => builder(tables[t] ?? { data: [], error: null }));
}

function req() {
  return new NextRequest(`https://label.tera-ai.uk/api/labeling-v3/blind/${CLIP}/file/url`);
}

describe('GET /api/labeling-v3/blind/[clipId]/file/url', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireProductionLabelingAccess.mockResolvedValue({ ok: true, userId: 'labeler-1', isOwner: false });
    presignGet.mockResolvedValue('https://r2.example/signed');
    setTables({
      motion_clip_review_slots: {
        data: [{ activity_day_kst: '2026-07-22', submitted_at: null, cohort_kind: 'live' }],
        error: null,
      },
      motion_clips: {
        data: [{ id: CLIP, started_at: 't', duration_sec: 30, r2_key: 'terra-clips/x.mp4', cameras: { name: '2번' } }],
        error: null,
      },
    });
  });

  it('does not sign before slot authorization (404 → no presign)', async () => {
    setTables({ motion_clip_review_slots: { data: [], error: null } });
    const res = await GET(req(), { params: { clipId: CLIP } });
    expect(res.status).toBe(404);
    expect(presignGet).not.toHaveBeenCalled();
  });

  it('signs r2_key after authorization and returns url only', async () => {
    const res = await GET(req(), { params: { clipId: CLIP } });
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.url).toBe('https://r2.example/signed');
    expect(body.expires_in).toBe(300);
    expect(JSON.stringify(body)).not.toContain('r2_key');
    expect(presignGet).toHaveBeenCalledWith('terra-clips/x.mp4', 300);
  });

  it('410 when media is missing', async () => {
    setTables({
      motion_clip_review_slots: {
        data: [{ activity_day_kst: '2026-07-22', submitted_at: null, cohort_kind: 'live' }],
        error: null,
      },
      motion_clips: { data: [{ id: CLIP, started_at: 't', duration_sec: 30, r2_key: null, cameras: { name: '2번' } }], error: null },
    });
    const res = await GET(req(), { params: { clipId: CLIP } });
    expect(res.status).toBe(410);
    expect(presignGet).not.toHaveBeenCalled();
  });

  it('502 on signing failure without raw text', async () => {
    presignGet.mockRejectedValue(new Error('aws creds boom'));
    const res = await GET(req(), { params: { clipId: CLIP } });
    expect(res.status).toBe(502);
    expect(JSON.stringify(await res.json())).not.toContain('boom');
  });

  it('403 for owner', async () => {
    requireProductionLabelingAccess.mockResolvedValue({ ok: true, userId: 'owner', isOwner: true });
    const res = await GET(req(), { params: { clipId: CLIP } });
    expect(res.status).toBe(403);
    expect(presignGet).not.toHaveBeenCalled();
  });
});
