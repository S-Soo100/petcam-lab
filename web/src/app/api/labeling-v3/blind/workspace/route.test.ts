import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { requireProductionLabelingAccess, rpc } = vi.hoisted(() => ({
  requireProductionLabelingAccess: vi.fn(),
  rpc: vi.fn(),
}));
vi.mock('@/lib/labelingAccess', () => ({ requireProductionLabelingAccess }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));

import { GET } from './route';

function req() {
  return new NextRequest('https://label.tera-ai.uk/api/labeling-v3/blind/workspace');
}

function workspaceRow(overrides: Record<string, unknown> = {}) {
  return {
    group_id: 'g1',
    group_name: 'A그룹',
    priority_activity_day: '2026-07-22',
    oldest_unlocked_activity_day: '2026-07-22',
    available_days: ['2026-07-22'],
    clip_total: 100,
    own_submitted: 34,
    partner_submitted: 28,
    agreed_count: 22,
    conflict_count: 4,
    awaiting_count: 74,
    late_added_count: 0,
    members: [
      { display_name: '크랑이아빠', submitted_count: 34, label_count: 20 },
      { display_name: '파트너', submitted_count: 28 },
    ],
    ...overrides,
  };
}

describe('GET /api/labeling-v3/blind/workspace', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireProductionLabelingAccess.mockResolvedValue({ ok: true, userId: 'labeler-1', isOwner: false });
    rpc.mockImplementation((fn: string) => {
      if (fn === 'fn_ensure_motion_review_slots') return Promise.resolve({ data: 3, error: null });
      return Promise.resolve({ data: [workspaceRow()], error: null });
    });
  });

  it('401 when unauthenticated (passes guard response through)', async () => {
    requireProductionLabelingAccess.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: 'unauthorized' }, { status: 401 }),
    });
    const res = await GET(req());
    expect(res.status).toBe(401);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('403 for owner (owner uses owner routes)', async () => {
    requireProductionLabelingAccess.mockResolvedValue({ ok: true, userId: 'owner', isOwner: true });
    const res = await GET(req());
    expect(res.status).toBe(403);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('materializes late slots then returns aggregate-only workspace, id from bearer', async () => {
    const res = await GET(req());
    expect(res.status).toBe(200);
    const ensureCall = rpc.mock.calls.find((c) => c[0] === 'fn_ensure_motion_review_slots');
    const wsCall = rpc.mock.calls.find((c) => c[0] === 'fn_get_motion_blind_workspace');
    expect(ensureCall?.[1].p_reviewer_id).toBe('labeler-1');
    expect(wsCall?.[1]).toEqual({ p_reviewer_id: 'labeler-1' });
    // ensure is called before workspace
    expect(rpc.mock.calls[0][0]).toBe('fn_ensure_motion_review_slots');
    const body = await res.json();
    expect(body.workspace.own_submitted).toBe(34);
    expect(body.workspace.partner_submitted).toBe(28);
  });

  it('exposes member submitted counts but not partner decision distribution', async () => {
    const res = await GET(req());
    const json = JSON.stringify(await res.json());
    expect(json).toContain('submitted_count');
    expect(json).not.toContain('label_count');
    expect(json).not.toContain('peer');
  });

  it('maps a stable SQLSTATE from ensure to 409 without DB text', async () => {
    rpc.mockImplementation((fn: string) => {
      if (fn === 'fn_ensure_motion_review_slots')
        return Promise.resolve({ data: null, error: { code: 'PT425', message: 'group_invariant raw' } });
      return Promise.resolve({ data: [workspaceRow()], error: null });
    });
    const res = await GET(req());
    expect(res.status).toBe(409);
    expect(JSON.stringify(await res.json())).not.toContain('raw');
  });

  it('maps unknown DB error to 502 without raw message', async () => {
    rpc.mockImplementation((fn: string) => {
      if (fn === 'fn_ensure_motion_review_slots') return Promise.resolve({ data: 3, error: null });
      return Promise.resolve({ data: null, error: { code: '08006', message: 'motion_clips connection lost' } });
    });
    const res = await GET(req());
    expect(res.status).toBe(502);
    expect(JSON.stringify(await res.json())).not.toContain('motion_clips');
  });
});
