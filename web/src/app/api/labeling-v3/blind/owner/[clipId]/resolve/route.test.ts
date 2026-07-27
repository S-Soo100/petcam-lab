import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { requireOwner, rpc, ownerClip, ownerScope } = vi.hoisted(() => ({
  requireOwner: vi.fn(),
  rpc: vi.fn(),
  ownerClip: vi.fn(),
  ownerScope: vi.fn(),
}));
vi.mock('@/lib/labelingAccess', () => ({ requireOwner }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));
vi.mock('../../../_access', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../_access')>()),
  getOwnerClipDuration: ownerClip,
  loadOwnerConflictScope: ownerScope,
}));

import { POST } from './route';

// 실제 clip duration 안에서 시작<끝인 유효 label GT(segment 하나).
function gtSegment(startSec: number, endSec: number) {
  return {
    visibility: 'visible',
    primary_action: 'moving',
    observed_actions: ['moving'],
    segments: [{ action: 'moving', start_sec: startSec, end_sec: endSec }],
    target: 'none',
    human_confidence: 'certain',
    context_tags: [],
    activity_intensity: null,
    highlight_recommendation: 'exclude',
    enrichment_object: 'none',
    interaction_types: [],
    note: null,
  };
}

const CLIP = '11111111-1111-4111-8111-111111111111';
const COHORT = '22222222-2222-4222-8222-222222222222';
const UPDATED = '2026-07-22T00:00:00Z';

function req(body: unknown, qs = '') {
  return new NextRequest(`https://label.tera-ai.uk/api/labeling-v3/blind/owner/${CLIP}/resolve${qs}`, {
    method: 'POST',
    body: JSON.stringify(body),
    headers: { 'content-type': 'application/json' },
  });
}

describe('POST owner/[clipId]/resolve', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireOwner.mockResolvedValue({ ok: true, userId: 'owner' });
    rpc.mockResolvedValue({ data: [{ status: 'owner_resolved' }], error: null });
    ownerClip.mockResolvedValue(60);
    ownerScope.mockResolvedValue({
      ok: true,
      scope: { cohortKind: 'live', cohortId: null },
    });
  });

  it('403 for a labeler', async () => {
    requireOwner.mockResolvedValue({ ok: false, response: NextResponse.json({ detail: 'forbidden' }, { status: 403 }) });
    expect((await POST(req({ choice: 'a', expected_updated_at: UPDATED }), { params: { clipId: CLIP } })).status).toBe(403);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('accepts choice a/b and passes owner id + expected_updated_at', async () => {
    await POST(req({ choice: 'a', reason: '왼쪽 판정 채택', expected_updated_at: UPDATED }), { params: { clipId: CLIP } });
    const args = rpc.mock.calls[0][1];
    expect(args.p_actor_id).toBe('owner');
    expect(args.p_choice).toBe('a');
    expect(args.p_expected_updated_at).toBe(UPDATED);
    expect(args.p_cohort_kind).toBe('live');
    expect(args.p_cohort_id).toBeNull();
  });

  it('passes exact canary scope while preserving optimistic concurrency', async () => {
    ownerScope.mockResolvedValue({
      ok: true,
      scope: { cohortKind: 'canary', cohortId: COHORT },
    });
    await POST(
      req(
        { choice: 'b', reason: 'canary 판정', expected_updated_at: UPDATED },
        `?cohort_id=${COHORT}`,
      ),
      { params: { clipId: CLIP } },
    );
    expect(ownerScope).toHaveBeenCalledWith(COHORT);
    const args = rpc.mock.calls[0][1];
    expect(args.p_cohort_kind).toBe('canary');
    expect(args.p_cohort_id).toBe(COHORT);
    expect(args.p_expected_updated_at).toBe(UPDATED);
  });

  it('fails closed for malformed or missing canary scope before RPC', async () => {
    ownerScope.mockResolvedValueOnce({
      ok: false,
      response: NextResponse.json({ detail: '잘못된 cohort id' }, { status: 400 }),
    });
    expect(
      (await POST(req({ choice: 'a', expected_updated_at: UPDATED }, '?cohort_id=nope'), {
        params: { clipId: CLIP },
      })).status,
    ).toBe(400);

    ownerScope.mockResolvedValueOnce({
      ok: false,
      response: NextResponse.json({ detail: '대상을 찾을 수 없어.' }, { status: 404 }),
    });
    expect(
      (await POST(req({ choice: 'a', expected_updated_at: UPDATED }, `?cohort_id=${COHORT}`), {
        params: { clipId: CLIP },
      })).status,
    ).toBe(404);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('choice new requires a valid final decision', async () => {
    const res = await POST(req({ choice: 'new', final_decision: 'bogus', expected_updated_at: UPDATED }), { params: { clipId: CLIP } });
    expect(res.status).toBe(400);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('choice new + label requires a valid final GT', async () => {
    const res = await POST(req({ choice: 'new', final_decision: 'label', final_gt: { visibility: 'nope' }, expected_updated_at: UPDATED }), { params: { clipId: CLIP } });
    expect(res.status).toBe(400);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('choice new + hold does not require GT and passes null', async () => {
    await POST(req({ choice: 'new', final_decision: 'hold', expected_updated_at: UPDATED }), { params: { clipId: CLIP } });
    const args = rpc.mock.calls[0][1];
    expect(args.p_final_decision).toBe('hold');
    expect(args.p_final_gt).toBeNull();
  });

  it('agreed consensus cannot be silently resolved (PT426 -> 409)', async () => {
    rpc.mockResolvedValue({ data: null, error: { code: 'PT426', message: 'not_conflict raw' } });
    const res = await POST(req({ choice: 'a', expected_updated_at: UPDATED }), { params: { clipId: CLIP } });
    expect(res.status).toBe(409);
    expect((await res.json()).code).toBe('not_conflict');
  });

  it('stale expected_updated_at (PT409) -> 409', async () => {
    rpc.mockResolvedValue({ data: null, error: { code: 'PT409' } });
    const res = await POST(req({ choice: 'a', expected_updated_at: UPDATED }), { params: { clipId: CLIP } });
    expect(res.status).toBe(409);
  });

  it('rejects unknown body keys', async () => {
    const res = await POST(req({ choice: 'a', expected_updated_at: UPDATED, reviewer_id: 'forged' }), { params: { clipId: CLIP } });
    expect(res.status).toBe(400);
    expect(rpc).not.toHaveBeenCalled();
  });

  // ── 하드닝: owner final GT 도 실제 clip duration 으로 검증(3600 상한 제거) ──
  it('rejects an owner resolution segment past the actual clip duration', async () => {
    ownerClip.mockResolvedValue(30);
    const res = await POST(
      req({ choice: 'new', final_decision: 'label', final_gt: gtSegment(0, 30.001), expected_updated_at: UPDATED }),
      { params: { clipId: CLIP } },
    );
    expect(res.status).toBe(400);
    expect(rpc).not.toHaveBeenCalledWith('fn_resolve_motion_blind_consensus', expect.anything());
  });

  it('accepts an owner label GT within the actual clip duration', async () => {
    ownerClip.mockResolvedValue(30);
    await POST(
      req({ choice: 'new', final_decision: 'label', final_gt: gtSegment(0, 30), expected_updated_at: UPDATED }),
      { params: { clipId: CLIP } },
    );
    const args = rpc.mock.calls[0][1];
    expect(args.p_final_decision).toBe('label');
    expect(args.p_final_gt).not.toBeNull();
  });
});
