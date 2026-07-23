import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { requireProductionLabelingAccess, rpc } = vi.hoisted(() => ({
  requireProductionLabelingAccess: vi.fn(),
  rpc: vi.fn(),
}));
vi.mock('@/lib/labelingAccess', () => ({ requireProductionLabelingAccess }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));

import { GET } from './route';
import { encodeBlindCursor } from '@/lib/motionBlindReviewServer';

const CLIP = '11111111-1111-4111-8111-111111111111';

function req(qs = '?activity_day=2026-07-22') {
  return new NextRequest(`https://label.tera-ai.uk/api/labeling-v3/blind/queue${qs}`);
}

function row(overrides: Record<string, unknown> = {}) {
  return {
    clip_id: CLIP,
    camera_id: 'cam',
    camera_name: '2번',
    started_at: '2026-07-22T05:00:00.123456+09:00',
    duration_sec: 30,
    media_ready: true,
    activity_day_kst: '2026-07-22',
    lease_expires_at: null,
    ...overrides,
  };
}

describe('GET /api/labeling-v3/blind/queue', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireProductionLabelingAccess.mockResolvedValue({ ok: true, userId: 'labeler-1', isOwner: false });
    rpc.mockResolvedValue({ data: [], error: null });
  });

  it('401 passthrough, 403 for owner', async () => {
    requireProductionLabelingAccess.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: 'unauthorized' }, { status: 401 }),
    });
    expect((await GET(req())).status).toBe(401);
    requireProductionLabelingAccess.mockResolvedValue({ ok: true, userId: 'owner', isOwner: true });
    expect((await GET(req())).status).toBe(403);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('rejects a missing/invalid activity_day before RPC', async () => {
    for (const qs of ['', '?activity_day=2026-7-2', '?activity_day=nope']) {
      rpc.mockClear();
      expect((await GET(req(qs))).status, qs).toBe(400);
      expect(rpc, qs).not.toHaveBeenCalled();
    }
  });

  it('rejects a well-formed but non-existent calendar date before RPC', async () => {
    for (const qs of ['?activity_day=2026-02-29', '?activity_day=2026-04-31', '?activity_day=2026-13-01']) {
      rpc.mockClear();
      expect((await GET(req(qs))).status, qs).toBe(400);
      expect(rpc, qs).not.toHaveBeenCalled();
    }
  });

  it('rejects invalid limit before RPC', async () => {
    for (const qs of ['?activity_day=2026-07-22&limit=0', '?activity_day=2026-07-22&limit=abc', '?activity_day=2026-07-22&limit=101']) {
      rpc.mockClear();
      expect((await GET(req(qs))).status, qs).toBe(400);
      expect(rpc, qs).not.toHaveBeenCalled();
    }
  });

  it('passes live scope and bearer id to the RPC', async () => {
    await GET(req('?activity_day=2026-07-22&limit=10'));
    const args = rpc.mock.calls[0][1];
    expect(args.p_reviewer_id).toBe('labeler-1');
    expect(args.p_activity_day).toBe('2026-07-22');
    expect(args.p_cohort_kind).toBe('live');
    expect(args.p_cohort_id).toBeNull();
    expect(args.p_limit).toBe(11);
  });

  it('rejects a cursor copied across a different activity day before RPC', async () => {
    const cursor = encodeBlindCursor(
      { activityDay: '2026-07-21', cohortKind: 'live', cohortId: null },
      { startedAt: '2026-07-21T05:00:00.000000+09:00', id: CLIP },
    );
    const res = await GET(req(`?activity_day=2026-07-22&cursor=${cursor}`));
    expect(res.status).toBe(400);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('has_more + scope-embedded next_cursor', async () => {
    rpc.mockResolvedValue({
      data: [
        row({ clip_id: 'a1111111-1111-4111-8111-111111111111', started_at: '2026-07-22T05:00:00.500000+09:00' }),
        row({ clip_id: 'b1111111-1111-4111-8111-111111111111', started_at: '2026-07-22T04:00:00.123456+09:00' }),
        row({ clip_id: 'c1111111-1111-4111-8111-111111111111', started_at: '2026-07-22T03:00:00.000000+09:00' }),
      ],
      error: null,
    });
    const res = await GET(req('?activity_day=2026-07-22&limit=2'));
    const body = await res.json();
    expect(body.items).toHaveLength(2);
    expect(body.has_more).toBe(true);
    const { decodeBlindCursor } = await import('@/lib/motionBlindReviewServer');
    const pos = decodeBlindCursor(body.next_cursor, { activityDay: '2026-07-22', cohortKind: 'live', cohortId: null });
    expect(pos?.startedAt).toBe('2026-07-22T04:00:00.123456+09:00');
  });

  it('never leaks peer/r2_key fields', async () => {
    rpc.mockResolvedValue({
      data: [row({ r2_key: 'secret.mp4', peer_decision: 'exclude', peer_note: 'hidden' })],
      error: null,
    });
    const json = JSON.stringify(await (await GET(req())).json());
    expect(json).not.toContain('r2_key');
    expect(json).not.toContain('peer_');
    expect(json).not.toContain('hidden');
  });

  it('maps unknown DB error to 502 without raw text', async () => {
    rpc.mockResolvedValue({ data: null, error: { code: '08006', message: 'motion_clips connection lost' } });
    const res = await GET(req());
    expect(res.status).toBe(502);
    expect(JSON.stringify(await res.json())).not.toContain('motion_clips');
  });
});
