import { describe, expect, it, vi } from 'vitest';

import { collectQueuePage, type QueueTriageRow } from './labelingQueue';

function clip(id: string, startedAt: string) {
  return { id, started_at: startedAt, camera_id: 'camera-1' };
}

const noTriage = async (): Promise<QueueTriageRow[]> => [];

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
      fetchTriage: noTriage,
    });

    expect(fetchCandidates).toHaveBeenCalledTimes(2);
    expect(result.items.map((item) => item.id)).toEqual(['open-1']);
    expect(result.hasMore).toBe(true);
    // cursor 는 이제 복합 위치 객체 — 같은 started_at 여러 clip 을 id 로 결정론적으로 이어간다.
    expect(result.nextCursor).toEqual({ startedAt: '2026-07-11T02:00:00Z', id: 'open-1' });
  });

  it('returns an object cursor from the last visible item and preserves equal timestamps', async () => {
    const same = '2026-07-22T02:00:00Z';
    const rows = [
      clip('33333333-3333-4333-8333-333333333333', same),
      clip('22222222-2222-4222-8222-222222222222', same),
      clip('11111111-1111-4111-8111-111111111111', same),
    ];
    const result = await collectQueuePage({
      limit: 2,
      fetchCandidates: vi.fn().mockResolvedValue(rows),
      fetchStages: vi.fn().mockResolvedValue([]),
      fetchTriage: noTriage,
    });
    expect(result.items.map((row) => row.id)).toEqual(rows.slice(0, 2).map((row) => row.id));
    expect(result.nextCursor).toEqual({ startedAt: same, id: rows[1].id });
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
      fetchTriage: noTriage,
    });

    expect(result.items).toEqual([
      { ...clip('locked', '2026-07-12T02:00:00Z'), session_stage: 'gt_locked' },
      { ...clip('draft', '2026-07-12T01:00:00Z'), session_stage: null },
    ]);
    expect(JSON.stringify(result.items)).not.toContain('prediction_snapshot');
  });

  it('applies triage precedence per candidate batch (설계 §5.2, §9)', async () => {
    // 배치 1: 전부 제외 대상(30건 = batchSize) → 두 번째 후보 fetch 를 강제.
    const excludedBatch = [
      // pending quarantine → 제외
      clip('pending-q', '2026-07-12T23:00:00Z'),
      // owner skip → 제외
      clip('owner-skip', '2026-07-12T22:59:00Z'),
      // completed 세션은 triage(label+owner label)여도 무조건 제외
      clip('completed-sess', '2026-07-12T22:58:00Z'),
    ];
    while (excludedBatch.length < 30) {
      const i = excludedBatch.length;
      excludedBatch.push(clip(`filler-q-${i}`, `2026-07-12T${String(22 - (i % 22)).padStart(2, '0')}:00:00Z`));
    }
    // 배치 2: 포함 대상만.
    const includedBatch = [
      clip('owner-label', '2026-07-11T05:00:00Z'), // owner label over quarantine → 포함
      clip('system-label', '2026-07-11T04:00:00Z'), // system label → 포함
      clip('no-row', '2026-07-11T03:00:00Z'), // triage row 없음 → 포함
      clip('gt-locked', '2026-07-11T02:00:00Z'), // gt_locked → 포함 + session_stage
    ];

    const fetchCandidates = vi
      .fn()
      .mockResolvedValueOnce(excludedBatch)
      .mockResolvedValueOnce(includedBatch);

    const fetchStages = vi.fn(async (ids: string[]) => {
      const stages: { clip_id: string; stage: string }[] = [];
      if (ids.includes('completed-sess')) stages.push({ clip_id: 'completed-sess', stage: 'completed' });
      if (ids.includes('gt-locked')) stages.push({ clip_id: 'gt-locked', stage: 'gt_locked' });
      return stages;
    });

    const fetchTriage = vi.fn(async (ids: string[]): Promise<QueueTriageRow[]> => {
      const rows: QueueTriageRow[] = [];
      const add = (clip_id: string, suggested_route: 'label' | 'quarantine', owner_decision: 'label' | 'skip' | null) => {
        if (ids.includes(clip_id)) rows.push({ clip_id, suggested_route, owner_decision });
      };
      add('pending-q', 'quarantine', null);
      add('owner-skip', 'label', 'skip');
      add('completed-sess', 'label', 'label');
      add('owner-label', 'quarantine', 'label');
      add('system-label', 'label', null);
      for (let i = 0; i < 30; i += 1) add(`filler-q-${i}`, 'quarantine', null);
      return rows;
    });

    const result = await collectQueuePage({
      limit: 10,
      fetchCandidates,
      fetchStages,
      fetchTriage,
    });

    // 첫 배치 전부 제외 → 두 번째 후보 fetch.
    expect(fetchCandidates).toHaveBeenCalledTimes(2);
    // fetchTriage 는 각 후보 배치 ID 만 받는다(전역 NOT IN 금지).
    expect(fetchTriage).toHaveBeenNthCalledWith(1, excludedBatch.map((c) => c.id));
    expect(fetchTriage).toHaveBeenNthCalledWith(2, includedBatch.map((c) => c.id));

    expect(result.items.map((item) => item.id)).toEqual([
      'owner-label',
      'system-label',
      'no-row',
      'gt-locked',
    ]);
    expect(result.items.find((item) => item.id === 'gt-locked')?.session_stage).toBe('gt_locked');
    expect(result.hasMore).toBe(false);
  });
});
