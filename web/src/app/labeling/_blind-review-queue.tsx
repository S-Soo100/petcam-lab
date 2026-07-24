'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';

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
import {
  BLIND_TODAY_WINDOW_HINT,
  blindEmptyStateMessage,
  blindNextAvailableDay,
  blindPreviousWorkCta,
  blindTodayTitle,
} from './_blind-review-view';

// 라벨러 '오늘 작업' 큐(설계 §5.1). 기준일 = 가장 최근에 닫힌 활동일(달력의 오늘이 아님).
// 활동일을 모두 제출하면 자동으로 건너뛰지 않고, 사용자가 명시적으로 '이전 활동일 작업 보기'를
// 눌러 URL activity_day 로 이동한다. 상대 원문 0(집계만), day 변경 시 stale 응답 폐기.
export default function BlindReviewQueue() {
  const userId = useLabelingUserId();
  const router = useRouter();
  const searchParams = useSearchParams();
  const urlDay = searchParams.get('activity_day');

  const [workspace, setWorkspace] = useState<BlindWorkspace | null>(null);
  const [items, setItems] = useState<BlindQueueItem[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const genRef = useRef(createRequestGeneration());

  // 현재 작업 활동일 = URL 지정 우선, 없으면 workspace 우선 활동일.
  const selectedDay = urlDay ?? workspace?.priority_activity_day ?? null;

  const loadDay = useCallback(
    async (day: string, existing: BlindQueueItem[], cur: string | null) => {
      const gen = genRef.current;
      const mine = gen.next();
      try {
        const res: BlindQueueResponse = await getBlindQueue({ activityDay: day, cursor: cur });
        if (!gen.isCurrent(mine)) return; // day 가 바뀌었으면 stale 응답 폐기.
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
      genRef.current.next(); // day 전환 시 진행 중 응답 폐기.
      try {
        const ws = workspace ?? (await getBlindWorkspace());
        if (!alive) return;
        if (!workspace) setWorkspace(ws);
        const day = urlDay ?? ws.priority_activity_day ?? null;
        if (day) {
          await loadDay(day, [], null);
        } else {
          setItems([]);
          setCursor(null);
          setHasMore(false);
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
  }, [urlDay]);

  const emptyMessage = workspace ? blindEmptyStateMessage(workspace) : null;
  const dayEmpty = !loading && items.length === 0;
  const nextDay = useMemo(
    () => (workspace ? blindNextAvailableDay(workspace, selectedDay) : null),
    [workspace, selectedDay],
  );
  const previousCta = workspace ? blindPreviousWorkCta(workspace) : null;

  // 전체·완료·남은 건수(설계 §5.1). 우선 활동일이면 workspace 집계, 아니면 로드된 건수만.
  const counts =
    workspace && selectedDay === workspace.priority_activity_day
      ? {
          total: workspace.clip_total,
          done: workspace.own_submitted,
          remaining: Math.max(workspace.clip_total - workspace.own_submitted, 0),
        }
      : null;

  return (
    <main className="mx-auto max-w-3xl space-y-3 px-4 py-6">
      <BlindReviewOnboarding userId={userId} />

      <div className="min-w-0">
        <h1 className="whitespace-nowrap text-xl font-semibold tracking-tight text-zinc-900">
          {blindTodayTitle(selectedDay)}
        </h1>
        <p className="text-xs text-zinc-500">{BLIND_TODAY_WINDOW_HINT}</p>
        {counts && (
          <p className="mt-1 text-sm text-zinc-700">
            전체 {counts.total} · 완료 {counts.done} · 남은 {counts.remaining}
          </p>
        )}
      </div>

      {workspace && <BlindReviewProgress workspace={workspace} />}

      {loading && <p className="text-sm text-zinc-500">불러오는 중…</p>}
      {error && <Card className="border-rose-200 bg-rose-50 text-sm text-rose-800">{error}</Card>}

      {dayEmpty && (
        <Card className="space-y-3 text-sm text-zinc-700">
          <p>{emptyMessage ?? '이 활동일에는 남은 작업이 없어.'}</p>
          {previousCta && nextDay && (
            <Button
              variant="labelingSecondary"
              size="md"
              onClick={() => router.replace(`/labeling?activity_day=${nextDay}`)}
            >
              {previousCta}
            </Button>
          )}
        </Card>
      )}

      {!loading && selectedDay && items.length > 0 && (
        <ul className="space-y-2">
          {items.map((item) => (
            <li key={item.id}>
              <Link
                href={`/labeling/blind/${item.id}?activity_day=${selectedDay}`}
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

      {!loading && hasMore && selectedDay && (
        <Button
          variant="labelingSecondary"
          size="md"
          className="w-full"
          onClick={() => loadDay(selectedDay, items, cursor)}
        >
          더 불러오기
        </Button>
      )}
    </main>
  );
}
