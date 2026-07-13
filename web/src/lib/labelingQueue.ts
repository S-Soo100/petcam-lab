export interface QueueCandidate {
  id: string;
  started_at: string;
  [key: string]: unknown;
}

export interface QueueSessionStage {
  clip_id: string;
  stage: string;
}

export type QueueItem<T extends QueueCandidate> = T & {
  session_stage: 'gt_locked' | null;
};

export interface QueuePage<T extends QueueCandidate> {
  items: QueueItem<T>[];
  hasMore: boolean;
  nextCursor: string | null;
}

// 완료 UUID 전체를 PostgREST NOT IN URL에 직렬화하지 않는다. 제한된 clip 후보를
// 가져온 뒤 해당 후보의 본인 session stage만 조회하고, 페이지가 찰 때까지 더 오래된
// 후보를 이어서 읽는다.
export async function collectQueuePage<T extends QueueCandidate>({
  limit,
  cursor,
  fetchCandidates,
  fetchStages,
}: {
  limit: number;
  cursor?: string | null;
  fetchCandidates: (cursor: string | null, batchSize: number) => Promise<T[]>;
  fetchStages: (clipIds: string[]) => Promise<QueueSessionStage[]>;
}): Promise<QueuePage<T>> {
  const batchSize = Math.min(Math.max(limit * 2, 30), 100);
  const available: QueueItem<T>[] = [];
  let scanCursor = cursor ?? null;
  let exhausted = false;

  while (available.length < limit + 1 && !exhausted) {
    const candidates = await fetchCandidates(scanCursor, batchSize);
    if (candidates.length === 0) break;

    const stages = await fetchStages(candidates.map((candidate) => candidate.id));
    const stageByClip = new Map(stages.map((row) => [row.clip_id, row.stage]));

    for (const candidate of candidates) {
      const stage = stageByClip.get(candidate.id);
      if (stage === 'completed') continue;
      available.push({
        ...candidate,
        session_stage: stage === 'gt_locked' ? 'gt_locked' : null,
      });
      if (available.length >= limit + 1) break;
    }

    scanCursor = candidates[candidates.length - 1].started_at;
    exhausted = candidates.length < batchSize;
  }

  const hasMore = available.length > limit;
  const items = available.slice(0, limit);
  return {
    items,
    hasMore,
    nextCursor: hasMore ? items[items.length - 1]?.started_at ?? null : null,
  };
}
