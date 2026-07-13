import { describe, expect, it, vi } from 'vitest';

import { collectQueuePage } from './labelingQueue';

function clip(id: string, startedAt: string) {
  return { id, started_at: startedAt, camera_id: 'camera-1' };
}

describe('collectQueuePage', () => {
  it('keeps scanning bounded candidate batches instead of serializing every completed id', async () => {
    const first = Array.from({ length: 30 }, (_, index) =>
      clip(`done-${index}`, `2026-07-12T${String(23 - (index % 23)).padStart(2, '0')}:00:00Z`),
    );
    const second = [
      clip('open-1', '2026-07-11T02:00:00Z'),
      clip('open-2', '2026-07-11T01:00:00Z'),
    ];
    const fetchCandidates = vi
      .fn()
      .mockResolvedValueOnce(first)
      .mockResolvedValueOnce(second);
    const fetchStages = vi.fn(async (ids: string[]) =>
      ids
        .filter((id) => id.startsWith('done-'))
        .map((clip_id) => ({ clip_id, stage: 'completed' })),
    );

    const result = await collectQueuePage({
      limit: 1,
      fetchCandidates,
      fetchStages,
    });

    expect(fetchCandidates).toHaveBeenCalledTimes(2);
    expect(result.items.map((item) => item.id)).toEqual(['open-1']);
    expect(result.hasMore).toBe(true);
    expect(result.nextCursor).toBe('2026-07-11T02:00:00Z');
  });

  it('excludes completed clips and exposes only gt_locked stage for resume', async () => {
    const fetchCandidates = vi.fn().mockResolvedValue([
      clip('completed', '2026-07-12T03:00:00Z'),
      clip('locked', '2026-07-12T02:00:00Z'),
      clip('draft', '2026-07-12T01:00:00Z'),
    ]);
    const fetchStages = vi.fn().mockResolvedValue([
      { clip_id: 'completed', stage: 'completed', prediction_snapshot: { action: 'drinking' } },
      { clip_id: 'locked', stage: 'gt_locked', prediction_snapshot: { action: 'moving' } },
    ]);

    const result = await collectQueuePage({
      limit: 30,
      fetchCandidates,
      fetchStages,
    });

    expect(result.items).toEqual([
      { ...clip('locked', '2026-07-12T02:00:00Z'), session_stage: 'gt_locked' },
      { ...clip('draft', '2026-07-12T01:00:00Z'), session_stage: null },
    ]);
    expect(JSON.stringify(result.items)).not.toContain('prediction_snapshot');
  });
});
