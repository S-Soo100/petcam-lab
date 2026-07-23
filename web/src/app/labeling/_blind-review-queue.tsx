'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';

import { Card } from '@/components/ui/Card';
import Button from '@/components/ui/Button';
import { ApiError } from '@/lib/labelingApi';
import { createRequestGeneration } from '@/lib/requestGeneration';
import { formatClipCapturedAt } from '@/lib/labelingV2';
import {
  getBlindQueue,
  getBlindWorkspace,
  type BlindQueueResponse,
} from '@/lib/motionBlindReviewApi';
import type { BlindQueueItem, BlindWorkspace } from '@/lib/motionBlindReviewServer';
import { useLabelingUserId } from './_owner-context';
import BlindReviewOnboarding from './_blind-review-onboarding';
import BlindReviewProgress from './_blind-review-progress';
import { blindEmptyStateMessage } from './_blind-review-view';

// 라벨러 활동일 큐(설계 §4). workspace → 서버가 준 priority_activity_day → 그 날짜 개인 큐를
// 최신순으로 로드한다. 상대 원문 0(집계만), 늦은 clip 배지, 빈 상태 안내, day/필터 변경 시 stale
// 응답 폐기(request generation). 스크롤은 reviewer+day 로 복원한다.
export default function BlindReviewQueue() {
  const userId = useLabelingUserId();
  const [workspace, setWorkspace] = useState<BlindWorkspace | null>(null);
  const [items, setItems] = useState<BlindQueueItem[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const genRef = useRef(createRequestGeneration());

  const loadDay = useCallback(
    async (day: string, existing: BlindQueueItem[], cur: string | null) => {
      const gen = genRef.current;
      const mine = gen.next();
      try {
        const res: BlindQueueResponse = await getBlindQueue({ activityDay: day, cursor: cur });
        if (!gen.isCurrent(mine)) return; // day/필터가 바뀌었으면 stale 응답 폐기.
        setItems(cur ? [...existing, ...res.items] : res.items);
        setCursor(res.next_cursor);
        setHasMore(res.has_more);
      } catch (e) {
        if (!genRef.current.isCurrent(mine)) return;
        setError(e instanceof ApiError ? e.message : (e as Error).message);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  useEffect(() => {
    let alive = true;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const ws = await getBlindWorkspace();
        if (!alive) return;
        setWorkspace(ws);
        if (ws.priority_activity_day) {
          await loadDay(ws.priority_activity_day, [], null);
        } else {
          setItems([]);
        }
      } catch (e) {
        if (!alive) return;
        setError(e instanceof ApiError ? e.message : (e as Error).message);
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const day = workspace?.priority_activity_day ?? null;
  const emptyMessage = workspace ? blindEmptyStateMessage(workspace) : null;

  return (
    <main className="mx-auto max-w-3xl space-y-3 px-4 py-6">
      <BlindReviewOnboarding userId={userId} />
      {workspace && <BlindReviewProgress workspace={workspace} />}

      {loading && <p className="text-sm text-zinc-500">불러오는 중…</p>}
      {error && <Card className="border-rose-200 bg-rose-50 text-sm text-rose-800">{error}</Card>}

      {!loading && emptyMessage && (
        <Card className="text-sm text-zinc-700">{emptyMessage}</Card>
      )}

      {!loading && day && items.length > 0 && (
        <ul className="space-y-2">
          {items.map((item) => (
            <li key={item.id}>
              <Link
                href={`/labeling/blind/${item.id}?activity_day=${day}`}
                className="block rounded-xl border border-zinc-200 bg-white p-3 text-sm shadow-sm hover:border-zinc-400"
              >
                <div className="font-medium text-zinc-900">{item.camera_name}</div>
                <div className="text-xs text-zinc-500">
                  {formatClipCapturedAt(item.started_at, item.duration_sec)}
                </div>
                {!item.media_ready && (
                  <div className="mt-1 text-xs text-rose-600">재생 준비 안 됨</div>
                )}
              </Link>
            </li>
          ))}
        </ul>
      )}

      {!loading && hasMore && day && (
        <Button
          variant="labelingSecondary"
          size="md"
          className="w-full"
          onClick={() => loadDay(day, items, cursor)}
        >
          더 불러오기
        </Button>
      )}
    </main>
  );
}
