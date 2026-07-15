import { describe, expect, it } from 'vitest';

import {
  decodeTriageCursor,
  encodeTriageCursor,
  mapTriageRowToDetail,
  mapTriageRowToListItem,
  parseTriageClipFilters,
  type TriageJoinRow,
} from './labelingTriageServer';

const OWNER_CLIP = '380d97fd-0000-4000-8000-000000000001';

function joinRow(overrides: Partial<TriageJoinRow> = {}): TriageJoinRow {
  return {
    clip_id: OWNER_CLIP,
    suggested_route: 'quarantine',
    suggestion_reason: 'gate_absent',
    suggestion_source: 'gate_activity_policy',
    policy_version: 'gate-v2',
    owner_decision: null,
    decided_at: null,
    decision_note: null,
    updated_at: '2026-07-15T00:00:00.000Z',
    // raw evidence 는 절대 응답에 새어나가면 안 된다 — 매퍼가 반드시 떨궈야 함.
    evidence_snapshot: {
      checkpoint: '/Users/baek/checkpoints/gate-v2.pt',
      producer_host: 'gecko-mac-mini.local',
      secret_token: 'AQ.super-secret',
    },
    camera_clips: {
      camera_id: 'cam-uuid-1',
      started_at: '2026-07-14T18:00:00.000Z',
      duration_sec: 42,
    },
    ...overrides,
  };
}

describe('triage cursor 인코딩/디코딩', () => {
  it('round-trip 이 정확히 복원된다', () => {
    const cursor = { updatedAt: '2026-07-15T00:00:00.000Z', clipId: OWNER_CLIP };
    expect(decodeTriageCursor(encodeTriageCursor(cursor))).toEqual(cursor);
  });

  it('잘못된 base64 를 거부한다', () => {
    expect(() => decodeTriageCursor('!!!not-base64!!!')).toThrow();
  });

  it('잘못된 날짜를 거부한다', () => {
    const bad = Buffer.from(
      JSON.stringify({ updatedAt: 'not-a-date', clipId: OWNER_CLIP }),
    ).toString('base64url');
    expect(() => decodeTriageCursor(bad)).toThrow();
  });

  it('UUID 아닌 clipId 를 거부한다', () => {
    const bad = Buffer.from(
      JSON.stringify({ updatedAt: '2026-07-15T00:00:00.000Z', clipId: 'not-a-uuid' }),
    ).toString('base64url');
    expect(() => decodeTriageCursor(bad)).toThrow();
  });
});

describe('owner-safe 매핑 — raw evidence 비노출(설계 §7, §8)', () => {
  it('목록 매퍼는 evidence/checkpoint/host 를 담지 않는다', () => {
    const item = mapTriageRowToListItem(joinRow());
    const json = JSON.stringify(item);
    expect(json).not.toContain('evidence_snapshot');
    expect(json).not.toContain('checkpoint');
    expect(json).not.toContain('producer_host');
    expect(json).not.toContain('secret_token');
    expect(item.reason_label).toBe('게코가 보이지 않을 가능성이 높음');
    expect(item.effective_state).toBe('pending');
    expect(item.camera_id).toBe('cam-uuid-1');
    expect(item.started_at).toBe('2026-07-14T18:00:00.000Z');
  });

  it('상세 매퍼는 최소 provenance 만 노출하고 raw evidence 는 제외한다', () => {
    const detail = mapTriageRowToDetail(joinRow());
    const json = JSON.stringify(detail);
    expect(json).not.toContain('evidence_snapshot');
    expect(json).not.toContain('checkpoint');
    expect(json).not.toContain('producer_host');
    expect(detail.suggestion_source).toBe('gate_activity_policy');
    expect(detail.policy_version).toBe('gate-v2');
  });

  it('owner label 결정을 labeled 로 반영한다', () => {
    const item = mapTriageRowToListItem(
      joinRow({ owner_decision: 'label', decided_at: '2026-07-15T01:00:00.000Z' }),
    );
    expect(item.effective_state).toBe('labeled');
  });
});

describe('parseTriageClipFilters — 촬영일·카메라 필터 검증(설계 §8.1)', () => {
  const sp = (q: string) => new URLSearchParams(q);

  it('빈 쿼리는 빈 필터', () => {
    expect(parseTriageClipFilters(sp(''))).toEqual({ filters: {} });
  });

  it('유효한 날짜·카메라를 통과시킨다', () => {
    const result = parseTriageClipFilters(
      sp(`date_from=2026-07-01T00:00:00%2B09:00&camera_id=${OWNER_CLIP}`),
    );
    expect(result).toEqual({
      filters: { dateFrom: '2026-07-01T00:00:00+09:00', dateTo: undefined, cameraId: OWNER_CLIP },
    });
  });

  it('잘못된 날짜를 거부한다', () => {
    expect(parseTriageClipFilters(sp('date_to=not-a-date'))).toHaveProperty('error');
  });

  it('UUID 아닌 카메라를 거부한다', () => {
    expect(parseTriageClipFilters(sp('camera_id=bogus'))).toHaveProperty('error');
  });
});
