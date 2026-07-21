import { describe, expect, it } from 'vitest';
import { mergeNewestQueueItems } from './labelingQueueClient';

describe('mergeNewestQueueItems', () => {
  it('deduplicates by id and sorts started_at/id descending', () => {
    const rows = mergeNewestQueueItems(
      [{ id: 'a', started_at: '2026-07-22T01:00:00Z' }],
      [
        { id: 'a', started_at: '2026-07-22T01:00:00Z' },
        { id: 'c', started_at: '2026-07-22T02:00:00Z' },
        { id: 'b', started_at: '2026-07-22T02:00:00Z' },
      ],
    );
    // 동률(02:00) 은 id DESC 로 c → b, 그 다음 오래된 a.
    expect(rows.map((row) => row.id)).toEqual(['c', 'b', 'a']);
  });

  it('keeps a single row per id even when a clip repeats across responses', () => {
    const rows = mergeNewestQueueItems(
      [{ id: 'b', started_at: '2026-07-22T02:00:00Z' }],
      [{ id: 'b', started_at: '2026-07-22T02:00:00Z' }],
    );
    expect(rows).toHaveLength(1);
  });

  it('re-sorts a reversed incoming page into newest-first order', () => {
    const rows = mergeNewestQueueItems(
      [] as { id: string; started_at: string }[],
      [
        { id: 'a', started_at: '2026-07-22T01:00:00Z' },
        { id: 'b', started_at: '2026-07-22T03:00:00Z' },
        { id: 'c', started_at: '2026-07-22T02:00:00Z' },
      ],
    );
    expect(rows.map((row) => row.id)).toEqual(['b', 'c', 'a']);
  });

  // F1 회귀 — ISO 문자열 사전순 비교는 실제 시간순과 다르다.
  // '.100000+00:00'(문자 '1')은 사전순으로 '+00:00'(문자 '+')보다 뒤로 가지만
  // 실제로는 100ms 더 최신이라 최신순에서 앞에 와야 한다.
  it('orders fractional-second timestamps by true epoch, not lexicographically', () => {
    const older = {
      id: '11111111-1111-4111-8111-111111111111',
      started_at: '2026-07-22T01:00:00+00:00',
    };
    const newer = {
      id: '22222222-2222-4222-8222-222222222222',
      started_at: '2026-07-22T01:00:00.100000+00:00',
    };
    const rows = mergeNewestQueueItems([older], [newer]);
    expect(rows.map((row) => row.id)).toEqual([newer.id, older.id]);
  });

  // 같은 instant 를 다르게 표기하면 epoch 가 같으므로 id DESC 로 tie-break 한다.
  it('breaks ties by id DESC when two timestamp representations name the same instant', () => {
    const a = {
      id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      started_at: '2026-07-22T01:00:00Z',
    };
    const b = {
      id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
      started_at: '2026-07-21T20:00:00-05:00',
    };
    const rows = mergeNewestQueueItems([a], [b]);
    // 2026-07-22T01:00:00Z === 2026-07-21T20:00:00-05:00 → id DESC → b 먼저.
    expect(rows.map((row) => row.id)).toEqual([b.id, a.id]);
  });

  // P1 회귀 — Date.parse 는 밀리초(3자리)까지만 본다. PostgreSQL timestamptz 는
  // 마이크로초(6자리)를 저장하므로, 밀리초 이후 자릿수까지 비교해 sub-millisecond 순서를 살린다.
  it('orders sub-millisecond timestamps by microsecond, not just by parsed millisecond', () => {
    // Date.parse('.123400Z') === Date.parse('.123499Z') 이지만 .123499 가 99µs 더 최신.
    const earlier = {
      id: '11111111-1111-4111-8111-111111111111',
      started_at: '2026-07-22T01:00:00.123400Z',
    };
    const later = {
      id: '22222222-2222-4222-8222-222222222222',
      started_at: '2026-07-22T01:00:00.123499Z',
    };
    const rows = mergeNewestQueueItems([earlier], [later]);
    expect(rows.map((row) => row.id)).toEqual([later.id, earlier.id]);
  });

  // API 에서는 올 수 없는 malformed timestamp 라도 comparator 가 NaN 을 반환하면 안 된다.
  // 결정론적 fallback = raw string DESC 후 id DESC.
  it('sorts deterministically without NaN for malformed timestamps', () => {
    const rows = mergeNewestQueueItems(
      [] as { id: string; started_at: string }[],
      [
        { id: 'x', started_at: 'not-a-date' },
        { id: 'y', started_at: 'zzz-invalid' },
      ],
    );
    // 둘 다 파싱 불가 → raw string DESC: 'zzz-invalid' > 'not-a-date' → y 먼저.
    expect(rows.map((row) => row.id)).toEqual(['y', 'x']);
  });
});
