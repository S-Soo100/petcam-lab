import { describe, expect, it } from 'vitest';

import {
  buildLibraryPage,
  encodeRoleCursor,
  mapHistoryRow,
  mapLibraryRow,
  mapOwnerOverview,
  parseHistoryFilters,
  parseLibraryFilters,
  parseRoleCursor,
  previousClosedActivityDay,
  type HistoryRow,
  type LibraryRow,
} from './labelingRoleServer';

const UUID_A = '11111111-1111-4111-8111-111111111111';
const UUID_B = '22222222-2222-4222-8222-222222222222';

function sp(params: Record<string, string | string[]>): URLSearchParams {
  const search = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (Array.isArray(v)) v.forEach((x) => search.append(k, x));
    else search.set(k, v);
  }
  return search;
}

describe('parseRoleCursor', () => {
  const scope = 'library|||||||';

  it('null/빈 문자열은 커서 없음', () => {
    expect(parseRoleCursor(null, scope)).toEqual({ ok: true, value: null });
    expect(parseRoleCursor('', scope)).toEqual({ ok: true, value: null });
  });

  it('마이크로초 timestamp 를 그대로 round-trip 한다', () => {
    const t = '2026-07-22T10:00:00.123456+00:00';
    const token = encodeRoleCursor({ t, id: UUID_A }, scope);
    const parsed = parseRoleCursor(token, scope);
    expect(parsed.ok).toBe(true);
    if (parsed.ok) {
      expect(parsed.value?.t).toBe(t); // PostgreSQL timestamp 텍스트 보존
      expect(parsed.value?.id).toBe(UUID_A);
    }
  });

  it('깨진 base64/JSON 은 400', () => {
    const res = parseRoleCursor('!!!not-base64!!!', scope);
    expect(res.ok).toBe(false);
    if (!res.ok) expect(res.response.status).toBe(400);
  });

  it('필드 누락(부분 커서)은 400', () => {
    const partial = Buffer.from(JSON.stringify({ v: 1, t: '2026-07-22T10:00:00Z' }), 'utf8').toString(
      'base64url',
    );
    expect(parseRoleCursor(partial, scope).ok).toBe(false);
  });

  it('scope 불일치(다른 필터에서 복사한 커서)는 400', () => {
    const token = encodeRoleCursor({ t: '2026-07-22T10:00:00Z', id: UUID_A }, scope);
    expect(parseRoleCursor(token, 'library|final||||||').ok).toBe(false);
  });
});

describe('parseLibraryFilters', () => {
  it('기본값: limit 30, 필터 없음', () => {
    const res = parseLibraryFilters(sp({}));
    expect(res.ok).toBe(true);
    if (res.ok) {
      expect(res.value.limit).toBe(30);
      expect(res.value.rpc.p_label_state).toBeNull();
      expect(res.value.rpc.p_camera_ids).toBeNull();
    }
  });

  it('limit 0/101 은 400', () => {
    expect(parseLibraryFilters(sp({ limit: '0' })).ok).toBe(false);
    expect(parseLibraryFilters(sp({ limit: '101' })).ok).toBe(false);
    expect(parseLibraryFilters(sp({ limit: '100' })).ok).toBe(true);
  });

  it('잘못된 label_state/label_source 는 400', () => {
    expect(parseLibraryFilters(sp({ label_state: 'nope' })).ok).toBe(false);
    expect(parseLibraryFilters(sp({ label_source: 'nope' })).ok).toBe(false);
    expect(parseLibraryFilters(sp({ label_state: 'final', label_source: 'blind_consensus' })).ok).toBe(
      true,
    );
  });

  it('re_review label_state 는 허용된다(review-fix P0-1)', () => {
    expect(parseLibraryFilters(sp({ label_state: 're_review' })).ok).toBe(true);
  });

  it('final_decision 은 서버 필터로 RPC 에 전달, 잘못된 값은 400(review-fix P1-2)', () => {
    const res = parseLibraryFilters(sp({ final_decision: 'exclude' }));
    expect(res.ok).toBe(true);
    if (res.ok) expect(res.value.rpc.p_final_decision).toBe('exclude');
    // 기본값 null.
    const none = parseLibraryFilters(sp({}));
    if (none.ok) expect(none.value.rpc.p_final_decision).toBeNull();
    // allowlist 밖은 400.
    expect(parseLibraryFilters(sp({ final_decision: 'nope' })).ok).toBe(false);
  });

  it('final_decision 은 cursor scope 에 포함돼 다른 필터 커서를 재사용 못한다(review-fix P1-2)', () => {
    const withExclude = parseLibraryFilters(sp({ final_decision: 'exclude' }));
    const withLabel = parseLibraryFilters(sp({ final_decision: 'label' }));
    expect(withExclude.ok && withLabel.ok).toBe(true);
    if (withExclude.ok && withLabel.ok) {
      expect(withExclude.value.scope).not.toBe(withLabel.value.scope);
    }
  });

  it('24:00 같은 잘못된 시간대는 400, both-or-neither 강제', () => {
    expect(parseLibraryFilters(sp({ time_from: '24:00', time_to: '06:00' })).ok).toBe(false);
    expect(parseLibraryFilters(sp({ time_from: '22:00' })).ok).toBe(false);
    expect(parseLibraryFilters(sp({ time_from: '22:00', time_to: '06:00' })).ok).toBe(true);
  });

  it('모든 카메라 id 를 배열로 받고 그룹 필터를 붙이지 않는다', () => {
    const res = parseLibraryFilters(sp({ camera_id: [UUID_A, UUID_B] }));
    expect(res.ok).toBe(true);
    if (res.ok) expect(res.value.rpc.p_camera_ids).toEqual([UUID_A, UUID_B]);
    expect(parseLibraryFilters(sp({ camera_id: 'not-a-uuid' })).ok).toBe(false);
  });

  it('날짜 범위를 KST 경계 timestamptz 로 변환한다', () => {
    const res = parseLibraryFilters(sp({ date_from: '2026-07-01', date_to: '2026-07-31' }));
    expect(res.ok).toBe(true);
    if (res.ok) {
      expect(res.value.rpc.p_date_from).toBe('2026-07-01T00:00:00+09:00');
      expect(res.value.rpc.p_date_to).toBe('2026-07-31T23:59:59.999+09:00');
    }
    expect(parseLibraryFilters(sp({ date_from: '2026-13-01' })).ok).toBe(false);
  });
});

describe('parseHistoryFilters', () => {
  it('decision/cohort_kind 검증 + cursor 는 submitted_at 축', () => {
    expect(parseHistoryFilters(sp({ decision: 'nope' })).ok).toBe(false);
    expect(parseHistoryFilters(sp({ cohort_kind: 'nope' })).ok).toBe(false);
    const res = parseHistoryFilters(sp({ decision: 'label', cohort_kind: 'live' }));
    expect(res.ok).toBe(true);
    if (res.ok) {
      expect(res.value.rpc.p_decision).toBe('label');
      expect(res.value.rpc.p_cohort_kind).toBe('live');
      expect('p_cursor_submitted_at' in res.value.rpc).toBe(true);
    }
  });
});

describe('mappers — 금지 필드 비노출(설계 §10)', () => {
  const forbidden = [
    'r2_key',
    'reviewer_id',
    'peer_decision',
    'digest',
    'lease_token',
    'prediction_snapshot',
    'rank_features',
    'evidence_snapshot',
  ];

  it('mapLibraryRow 는 주입된 금지 키를 버린다', () => {
    const row = {
      clip_id: UUID_A,
      camera_id: UUID_B,
      camera_name: '카메라',
      started_at: '2026-07-22T10:00:00Z',
      duration_sec: '30',
      label_state: 'final',
      label_source: 'blind_consensus',
      final_decision: 'label',
      final_gt: { behavior: 'moving' },
      r2_key: 'secret.mp4',
      reviewer_id: 'uuid',
      peer_decision: 'hold',
      digest: 'abc',
      lease_token: 'tok',
      prediction_snapshot: {},
      rank_features: {},
      evidence_snapshot: {},
    } as unknown as LibraryRow;
    const mapped = mapLibraryRow(row);
    expect(mapped.duration_sec).toBe(30);
    const json = JSON.stringify(mapped);
    for (const key of forbidden) expect(json).not.toContain(key);
  });

  it('mapHistoryRow 는 final_status 를 2단계로 접고 금지 키를 버린다', () => {
    const row = {
      submission_id: UUID_A,
      clip_id: UUID_B,
      camera_id: UUID_A,
      camera_name: '카메라',
      started_at: '2026-07-22T10:00:00Z',
      duration_sec: 30,
      media_ready: true,
      submitted_at: '2026-07-22T11:00:00Z',
      decision: 'label',
      reason_code: 'behavior_data',
      initial_gt: { behavior: 'moving' },
      note: '메모',
      cohort_kind: 'live',
      final_status: 'conflict',
      peer_decision: 'hold',
      digest: 'abc',
      reviewer_id: 'uuid',
    } as unknown as HistoryRow;
    const mapped = mapHistoryRow(row);
    // conflict 는 in_review 로 접혀 불일치 발생 여부를 숨긴다.
    expect(mapped.final_status).toBe('in_review');
    const json = JSON.stringify(mapped);
    for (const key of ['peer_decision', 'digest', 'reviewer_id']) {
      expect(json).not.toContain(key);
    }
  });

  it('mapOwnerOverview 는 display_name/count 만 남기고 이메일/UUID reviewer 를 버린다', () => {
    const raw = {
      activity_day: '2026-07-22',
      groups: [
        {
          group_id: UUID_A,
          group_name: 'A조',
          clip_total: 10,
          members: [
            { display_name: '라벨러 A', submitted_count: 8, email: 'a@x.com', reviewer_id: 'uuid-a' },
            { display_name: '라벨러 B', submitted_count: 7 },
          ],
          agreed_count: 5,
          conflict_count: 1,
          awaiting_count: 4,
        },
      ],
      open_canaries: [
        { cohort_id: UUID_B, label: '카나리', group_id: UUID_A, clip_total: 8, slot_total: 16, submitted_total: 15, conflict_count: 0 },
      ],
    };
    const mapped = mapOwnerOverview(raw);
    expect(mapped.groups[0].members[0].submitted_count).toBe(8);
    // review-fix P1-3: slot_total 분모(2×clip_total)를 매핑한다 → 15/16, not 15/8.
    expect(mapped.open_canaries[0].slot_total).toBe(16);
    expect(mapped.open_canaries[0].submitted_total).toBe(15);
    const json = JSON.stringify(mapped);
    expect(json).not.toContain('a@x.com');
    expect(json).not.toContain('reviewer_id');
    expect(json).not.toContain('uuid-a');
  });
});

describe('buildLibraryPage — keyset', () => {
  function row(id: string, t: string): LibraryRow {
    return {
      clip_id: id,
      camera_id: null,
      camera_name: null,
      started_at: t,
      duration_sec: 30,
      label_state: 'final',
      label_source: 'none',
      final_decision: null,
      final_gt: null,
    };
  }

  it('limit+1 이면 has_more + next_cursor(마지막 raw t/id)', () => {
    const filters = parseLibraryFilters(sp({ limit: '2' }));
    expect(filters.ok).toBe(true);
    if (!filters.ok) return;
    const rows = [
      row(UUID_A, '2026-07-22T10:00:00Z'),
      row(UUID_B, '2026-07-22T09:00:00Z'),
      row('33333333-3333-4333-8333-333333333333', '2026-07-22T08:00:00Z'),
    ];
    const page = buildLibraryPage(rows, filters.value);
    expect(page.items).toHaveLength(2);
    expect(page.has_more).toBe(true);
    // next_cursor 는 page 마지막(UUID_B, 09:00) 위치를 담아 같은 scope 로 재파싱된다.
    const reparsed = parseRoleCursor(page.next_cursor, filters.value.scope);
    expect(reparsed.ok).toBe(true);
    if (reparsed.ok) {
      expect(reparsed.value?.id).toBe(UUID_B);
      expect(reparsed.value?.t).toBe('2026-07-22T09:00:00Z');
    }
  });

  it('100-boundary: limit 100 + 101 rows(lookahead) → 100 노출 has_more true(review-fix P1-2)', () => {
    const filters = parseLibraryFilters(sp({ limit: '100' }));
    expect(filters.ok).toBe(true);
    if (!filters.ok) return;
    const rows: LibraryRow[] = Array.from({ length: 101 }, (_, i) =>
      row(
        `${String(i).padStart(8, '0')}-1111-4111-8111-111111111111`,
        `2026-07-22T${String(23 - (i % 24)).padStart(2, '0')}:00:00Z`,
      ),
    );
    const page = buildLibraryPage(rows, filters.value);
    expect(page.items).toHaveLength(100);
    expect(page.has_more).toBe(true);
    expect(page.next_cursor).not.toBeNull();
  });

  it('100-boundary: 정확히 100 rows(lookahead 없음) → has_more false', () => {
    const filters = parseLibraryFilters(sp({ limit: '100' }));
    if (!filters.ok) return;
    const rows: LibraryRow[] = Array.from({ length: 100 }, (_, i) =>
      row(`${String(i).padStart(8, '0')}-1111-4111-8111-111111111111`, '2026-07-22T10:00:00Z'),
    );
    const page = buildLibraryPage(rows, filters.value);
    expect(page.items).toHaveLength(100);
    expect(page.has_more).toBe(false);
    expect(page.next_cursor).toBeNull();
  });
});

describe('previousClosedActivityDay — 07:00 KST 경계', () => {
  it('KST 06:59 는 아직 전전날이 현재 활동일 → 직전 닫힘은 그 하루 전', () => {
    // 2026-07-22 06:59 KST = 2026-07-21T21:59:00Z. 현재 활동일=07-21, 직전 닫힘=07-20.
    expect(previousClosedActivityDay(new Date('2026-07-21T21:59:00Z'))).toBe('2026-07-20');
  });

  it('KST 07:01 는 그날이 현재 활동일 → 직전 닫힘은 하루 전', () => {
    // 2026-07-22 07:01 KST = 2026-07-21T22:01:00Z. 현재 활동일=07-22, 직전 닫힘=07-21.
    expect(previousClosedActivityDay(new Date('2026-07-21T22:01:00Z'))).toBe('2026-07-21');
  });
});
