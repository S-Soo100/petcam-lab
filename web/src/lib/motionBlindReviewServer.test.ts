import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { requireProductionLabelingAccess } = vi.hoisted(() => ({
  requireProductionLabelingAccess: vi.fn(),
}));
vi.mock('@/lib/labelingAccess', () => ({ requireProductionLabelingAccess }));

import {
  mapBlindQueueRow,
  mapBlindWorkspaceRow,
  mapBlindClipDetailRow,
  encodeBlindCursor,
  decodeBlindCursor,
  InvalidBlindCursorError,
  blindRpcErrorResponse,
  requireBlindLabeler,
  isValidActivityDay,
  type BlindQueueScope,
} from './motionBlindReviewServer';

const CLIP = '11111111-1111-4111-8111-111111111111';

function req() {
  return new NextRequest('https://label.tera-ai.uk/api/labeling-v3/blind/queue');
}

describe('isValidActivityDay — strict real calendar date (하드닝)', () => {
  it('accepts real dates incl. leap day, rejects non-existent calendar dates', () => {
    expect(isValidActivityDay('2024-02-29')).toBe(true); // 윤년
    expect(isValidActivityDay('2026-02-29')).toBe(false); // 평년엔 없는 날
    expect(isValidActivityDay('2026-04-31')).toBe(false); // 4월은 30일까지
    expect(isValidActivityDay('2026-13-01')).toBe(false); // 13월 없음
    expect(isValidActivityDay('2026-00-10')).toBe(false); // 0월 없음
    expect(isValidActivityDay('2026-07-00')).toBe(false); // 0일 없음
    expect(isValidActivityDay('2026-07-22')).toBe(true);
    expect(isValidActivityDay(null)).toBe(false);
    expect(isValidActivityDay('2026-7-2')).toBe(false); // 자릿수 불일치
  });
});

describe('mapBlindQueueRow — allowlist, no peer/secret leak', () => {
  it('never emits peer/secret/raw fields', () => {
    const raw = {
      clip_id: CLIP,
      camera_name: '2번 카메라',
      started_at: '2026-07-21T16:30:00.123456+09:00',
      duration_sec: 30,
      media_ready: true,
      activity_day_kst: '2026-07-21',
      lease_expires_at: null,
      peer_reviewer_id: 'secret-peer',
      peer_decision: 'exclude',
      peer_initial_gt: { visibility: 'absent' },
      peer_note: 'hidden',
      r2_key: 'terra-clips/secret.mp4',
      evidence_snapshot: { hidden: true },
      digest: 'deadbeef',
    };
    const json = JSON.stringify(mapBlindQueueRow(raw));
    for (const secret of [
      'peer_reviewer_id',
      'peer_decision',
      'peer_initial_gt',
      'peer_note',
      'r2_key',
      'evidence_snapshot',
      'digest',
      'secret-peer',
      'hidden',
    ]) {
      expect(json).not.toContain(secret);
    }
    expect(mapBlindQueueRow(raw).id).toBe(CLIP);
  });

  it('defaults camera name and coerces types', () => {
    const item = mapBlindQueueRow({
      clip_id: CLIP,
      started_at: 't',
      duration_sec: '30',
      media_ready: true,
      activity_day_kst: '2026-07-21',
    });
    expect(item.camera_name).toBe('이름 없는 카메라');
    expect(item.duration_sec).toBe(30);
    expect(item.lease_expires_at).toBeNull();
  });
});

describe('mapBlindWorkspaceRow — aggregate only', () => {
  it('exposes member submitted counts but never peer decision distribution', () => {
    const ws = mapBlindWorkspaceRow({
      group_id: 'g',
      group_name: 'A그룹',
      priority_activity_day: '2026-07-22',
      oldest_unlocked_activity_day: '2026-07-22',
      available_days: ['2026-07-22'],
      clip_total: '100',
      own_submitted: '34',
      partner_submitted: '28',
      agreed_count: '22',
      conflict_count: '4',
      awaiting_count: '74',
      late_added_count: '0',
      members: [
        { display_name: '크랑이아빠', submitted_count: 34, label_count: 20, hold_count: 5, exclude_count: 9 },
        { display_name: '파트너', submitted_count: 28 },
      ],
    });
    expect(ws.own_submitted).toBe(34);
    expect(ws.partner_submitted).toBe(28);
    expect(ws.members[0]).toEqual({ display_name: '크랑이아빠', submitted_count: 34 });
    const json = JSON.stringify(ws);
    expect(json).not.toContain('label_count');
    expect(json).not.toContain('hold_count');
    expect(json).not.toContain('exclude_count');
  });

  it('returns a safe empty shape when not assigned', () => {
    const ws = mapBlindWorkspaceRow({
      group_id: null,
      group_name: null,
      priority_activity_day: null,
      oldest_unlocked_activity_day: null,
      available_days: null,
      clip_total: 0,
      own_submitted: 0,
      partner_submitted: 0,
      agreed_count: 0,
      conflict_count: 0,
      awaiting_count: 0,
      late_added_count: 0,
      members: null,
    });
    expect(ws.group_id).toBeNull();
    expect(ws.available_days).toEqual([]);
    expect(ws.members).toEqual([]);
  });
});

describe('mapBlindClipDetailRow — no peer, no media key', () => {
  it('emits allowlisted detail only', () => {
    const detail = mapBlindClipDetailRow({
      clip_id: CLIP,
      camera_name: '2번',
      started_at: 't',
      duration_sec: 30,
      media_ready: true,
      activity_day_kst: '2026-07-21',
      cohort_kind: 'live',
      own_submitted: false,
      r2_key: 'secret.mp4',
      peer_decision: 'label',
      consensus_status: 'conflict',
    });
    const json = JSON.stringify(detail);
    expect(json).not.toContain('r2_key');
    expect(json).not.toContain('peer_decision');
    expect(json).not.toContain('consensus_status');
    expect(detail.cohort_kind).toBe('live');
    expect(detail.own_submitted).toBe(false);
  });
});

describe('blind queue cursor — scope embedded', () => {
  const liveScope: BlindQueueScope = { activityDay: '2026-07-22', cohortKind: 'live', cohortId: null };

  it('round-trips a live position', () => {
    const c = encodeBlindCursor(liveScope, { startedAt: '2026-07-22T05:00:00.123456+09:00', id: CLIP });
    const pos = decodeBlindCursor(c, liveScope);
    expect(pos?.startedAt).toBe('2026-07-22T05:00:00.123456+09:00');
    expect(pos?.id).toBe(CLIP);
  });

  it('returns null for empty cursor (first page)', () => {
    expect(decodeBlindCursor(null, liveScope)).toBeNull();
    expect(decodeBlindCursor('', liveScope)).toBeNull();
  });

  it('rejects a cursor copied to a different activity day', () => {
    const c = encodeBlindCursor(liveScope, { startedAt: '2026-07-22T05:00:00.000000+09:00', id: CLIP });
    expect(() =>
      decodeBlindCursor(c, { activityDay: '2026-07-21', cohortKind: 'live', cohortId: null }),
    ).toThrow(InvalidBlindCursorError);
  });

  it('rejects a cursor copied across live/canary scope', () => {
    const c = encodeBlindCursor(liveScope, { startedAt: '2026-07-22T05:00:00.000000+09:00', id: CLIP });
    expect(() =>
      decodeBlindCursor(c, { activityDay: '2026-07-22', cohortKind: 'canary', cohortId: CLIP }),
    ).toThrow(InvalidBlindCursorError);
  });

  it('rejects malformed base64/json', () => {
    expect(() => decodeBlindCursor('%%%not-base64', liveScope)).toThrow(InvalidBlindCursorError);
  });
});

describe('blindRpcErrorResponse — stable SQLSTATE mapping', () => {
  it.each([
    ['22023', 400, 'invalid_request'],
    ['P0002', 404, 'not_found'],
    ['PT403', 404, 'not_assigned'],
    ['PT409', 409, 'stale_state'],
    ['PT410', 409, 'already_submitted'],
    ['PT423', 409, 'slot_in_use'],
    ['PT424', 410, 'stale_lease'],
    ['PT425', 409, 'group_invariant'],
    ['PT426', 409, 'not_conflict'],
    ['PT427', 410, 'cohort_closed'],
  ])('maps %s -> %d', async (code, status, expectedCode) => {
    const res = blindRpcErrorResponse({ code });
    expect(res).not.toBeNull();
    expect(res!.status).toBe(status);
    expect((await res!.json()).code).toBe(expectedCode);
  });

  it('returns null for unknown codes so caller renders a 502', () => {
    expect(blindRpcErrorResponse({ code: '08006', message: 'connection lost' })).toBeNull();
  });
});

describe('requireBlindLabeler — labeler only, id from bearer', () => {
  beforeEach(() => vi.clearAllMocks());

  it('passes through the access guard failure', async () => {
    requireProductionLabelingAccess.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: 'unauthorized' }, { status: 401 }),
    });
    const r = await requireBlindLabeler(req());
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.response.status).toBe(401);
  });

  it('rejects owner with 403 (owner uses owner routes)', async () => {
    requireProductionLabelingAccess.mockResolvedValue({ ok: true, userId: 'owner', isOwner: true });
    const r = await requireBlindLabeler(req());
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.response.status).toBe(403);
  });

  it('returns the labeler user id from bearer', async () => {
    requireProductionLabelingAccess.mockResolvedValue({ ok: true, userId: 'labeler-1', isOwner: false });
    const r = await requireBlindLabeler(req());
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.userId).toBe('labeler-1');
  });
});
