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
});
