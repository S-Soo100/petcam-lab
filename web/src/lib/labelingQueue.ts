import {
  effectiveTriageState,
  isHiddenFromLabelingQueue,
  type TriageOwnerDecision,
  type TriageSuggestedRoute,
} from './labelingTriage';

export interface QueueCandidate {
  id: string;
  started_at: string;
  [key: string]: unknown;
}

export interface QueueSessionStage {
  clip_id: string;
  stage: string;
}

// 후보 배치의 triage 상태만 조회한다(설계 §9). suggested_route/owner_decision 로
// 유효 상태를 접어 pending/skipped 를 큐에서 제외한다. evidence 는 여기서 안 읽는다.
export interface QueueTriageRow {
  clip_id: string;
  suggested_route: TriageSuggestedRoute;
  owner_decision: TriageOwnerDecision | null;
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
  fetchTriage,
}: {
  limit: number;
  cursor?: string | null;
  fetchCandidates: (cursor: string | null, batchSize: number) => Promise<T[]>;
  fetchStages: (clipIds: string[]) => Promise<QueueSessionStage[]>;
  fetchTriage: (clipIds: string[]) => Promise<QueueTriageRow[]>;
}): Promise<QueuePage<T>> {
  const batchSize = Math.min(Math.max(limit * 2, 30), 100);
  const available: QueueItem<T>[] = [];
  let scanCursor = cursor ?? null;
  let exhausted = false;

  while (available.length < limit + 1 && !exhausted) {
    const candidates = await fetchCandidates(scanCursor, batchSize);
    if (candidates.length === 0) break;

    const ids = candidates.map((candidate) => candidate.id);
    // 세션 stage 와 triage 상태를 배치 단위로 동시에 읽는다(전역 NOT IN 금지).
    const [stages, triageRows] = await Promise.all([
      fetchStages(ids),
      fetchTriage(ids),
    ]);
    const stageByClip = new Map(stages.map((row) => [row.clip_id, row.stage]));
    const triageByClip = new Map(triageRows.map((row) => [row.clip_id, row]));

    for (const candidate of candidates) {
      const stage = stageByClip.get(candidate.id);
      // completed 세션은 triage 와 무관하게 먼저 제외한다.
      if (stage === 'completed') continue;
      // 이후 유효 triage 상태가 pending/skipped 면 제외. owner label / label / row 없음은 포함.
      const triage = triageByClip.get(candidate.id) ?? null;
      if (isHiddenFromLabelingQueue(effectiveTriageState(triage))) continue;
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
