'use client';

// motion_clips 운영 라벨링 큐 v3 — owner 전체 영상 / labeler 라벨 대기(설계 §5·§8).
//
// owner: 전체|라벨 대기|보류|제외 탭 + 카메라/미디어/날짜 필터. 최신 촬영순 기본.
// labeler: 탭 없이 label 큐 고정(state 는 서버가 강제). 카드 클릭 → /labeling/motion/{clipId}.
// 필터는 URL 에 영속하고, 늦게 온 이전 세대 응답은 request generation 으로 폐기한다.
// VLM/evidence 필드는 카드에 없다(GT 잠금 전 blind).

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';

import { ApiError, UnauthorizedError } from '@/lib/labelingApi';
import type { MotionLabelingState, MotionQueueItem } from '@/lib/labelingV3';
import { getMotionQueue } from '@/lib/labelingV3Api';
import {
  mergeMotionQueueItems,
  parseMotionQueueFilters,
  toMotionQueueQuery,
  type MotionQueueUiFilters,
} from '@/lib/labelingV3QueueClient';
import { createRequestGeneration } from '@/lib/requestGeneration';
import Badge from '@/components/ui/Badge';
import Button from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import MotionFilterBar from './_motion-filter-bar';
import { useIsOwner } from './_owner-context';

const PAGE_SIZE = 30;

const OWNER_TABS: readonly { key: MotionLabelingState | 'all'; label: string }[] = [
  { key: 'all', label: '전체 영상' },
  { key: 'label', label: '라벨 대기' },
  { key: 'hold', label: '보류' },
  { key: 'skip', label: '제외' },
];

const STATE_BADGE: Record<
  MotionLabelingState,
  { tone: 'neutral' | 'success' | 'warning'; label: string }
> = {
  unreviewed: { tone: 'neutral', label: '미분류' },
  label: { tone: 'success', label: '라벨 대상' },
  hold: { tone: 'warning', label: '보류' },
  skip: { tone: 'neutral', label: '제외' },
};

export default function MotionQueue() {
  const isOwner = useIsOwner();
  const router = useRouter();
  const searchParams = useSearchParams();
  const filters = useMemo(
    () => parseMotionQueueFilters(new URLSearchParams(searchParams.toString())),
    [searchParams],
  );

  const [items, setItems] = useState<MotionQueueItem[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [loadedOnce, setLoadedOnce] = useState(false);
  const gen = useRef(createRequestGeneration());

  const load = useCallback(
    async (nextCursor: string | null) => {
      const g = gen.current.next();
      if (nextCursor === null) {
        setItems([]);
        setCursor(null);
        setHasMore(false);
        setLoadedOnce(false);
      }
      setBusy(true);
      setErr(null);
      try {
        const resp = await getMotionQueue({
          limit: PAGE_SIZE,
          cursor: nextCursor ?? undefined,
          // labeler 는 항상 label 큐(서버가 state/media 를 강제하므로 넘기지 않는다).
          state: isOwner ? filters.state : undefined,
          cameraIds: filters.camera_id,
          dateFrom: filters.date_from,
          dateTo: filters.date_to,
          media: isOwner ? filters.media : undefined,
        });
        if (!gen.current.isCurrent(g)) return;
        setItems((prev) => mergeMotionQueueItems(nextCursor ? prev : [], resp.items));
        setCursor(resp.next_cursor);
        setHasMore(resp.has_more);
      } catch (e) {
        if (!gen.current.isCurrent(g)) return;
        if (e instanceof UnauthorizedError) {
          router.replace('/labeling/login');
          return;
        }
        setErr(e instanceof ApiError ? e.message : (e as Error).message);
      } finally {
        if (gen.current.isCurrent(g)) {
          setBusy(false);
          setLoadedOnce(true);
        }
      }
    },
    [router, filters, isOwner],
  );

  useEffect(() => {
    load(null);
    return () => {
      gen.current.next();
    };
  }, [load]);

  function applyFilters(next: MotionQueueUiFilters) {
    const qs = toMotionQueueQuery(next);
    router.replace(qs ? `/labeling/motion?${qs}` : '/labeling/motion');
  }

  return (
    <main className="mx-auto max-w-4xl space-y-6 px-6 py-8">
      <div className="flex items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-zinc-900">
            {isOwner ? '운영 영상 (motion clips)' : '라벨 대기 큐'}
          </h1>
          <p className="text-sm text-zinc-500">
            {isOwner
              ? '모든 운영 영상 최신 촬영순. 카드 → 직접 라벨링·분류.'
              : '보낸 영상만 (최신순). 클릭 → 단건 라벨링.'}
          </p>
        </div>
        <Button variant="secondary" size="sm" onClick={() => load(null)} disabled={busy}>
          {busy ? '불러오는 중…' : '↻ 새로고침'}
        </Button>
      </div>

      {isOwner && (
        <div className="flex flex-wrap gap-1.5">
          {OWNER_TABS.map((tab) => (
            <button
              key={tab.key}
              type="button"
              onClick={() => applyFilters({ ...filters, state: tab.key })}
              className={`rounded-md px-3 py-1 text-sm ring-1 ring-inset ${
                (filters.state ?? 'all') === tab.key
                  ? 'bg-zinc-900 text-white ring-zinc-900'
                  : 'text-zinc-600 ring-zinc-200 hover:bg-zinc-50'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      )}

      <MotionFilterBar value={filters} onChange={applyFilters} showMedia={isOwner} />

      {err && (
        <div className="rounded-md bg-red-50 px-4 py-3 text-sm text-red-700 ring-1 ring-inset ring-red-200">
          {err}
        </div>
      )}

      {loadedOnce && items.length === 0 && !busy && !err && (
        <Card padding="lg">
          <p className="text-sm text-zinc-600">
            {isOwner ? '해당 조건의 운영 영상이 없어요.' : '지금 라벨할 영상이 없어요.'}
          </p>
        </Card>
      )}

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {items.map((clip) => (
          <MotionCard key={clip.id} clip={clip} showState={isOwner} />
        ))}
      </div>

      {hasMore && (
        <div className="flex justify-center pt-2">
          <Button variant="secondary" onClick={() => load(cursor)} disabled={busy}>
            {busy ? '불러오는 중…' : '더보기'}
          </Button>
        </div>
      )}
    </main>
  );
}

function MotionCard({ clip, showState }: { clip: MotionQueueItem; showState: boolean }) {
  // client fetch 이후에만 렌더되므로(items 초기값 []) KST 포맷 hydration mismatch 없음.
  // timeZone 을 항상 명시한다(로케일/타임존 미지정 시 hydration mismatch).
  const startedAt = new Date(clip.started_at).toLocaleString('ko-KR', {
    timeZone: 'Asia/Seoul',
    hour12: false,
  });
  const dur = clip.duration_sec ? `${Math.round(clip.duration_sec)}s` : '?';
  const badge = STATE_BADGE[clip.state];

  return (
    <Link href={`/labeling/motion/${clip.id}`} prefetch={false}>
      <Card className="cursor-pointer transition-shadow hover:shadow-md">
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex flex-wrap items-center gap-1.5">
            {showState && <Badge tone={badge.tone}>{badge.label}</Badge>}
            {clip.session_stage === 'gt_locked' && <Badge tone="warning">AI 판정 검수 이어하기</Badge>}
            {!clip.media_ready && <Badge tone="neutral">원본 재생 불가</Badge>}
            <span className="text-xs text-zinc-500">{dur}</span>
          </div>
          <div className="text-sm font-medium tabular-nums text-zinc-800">{startedAt}</div>
          <div className="truncate text-xs text-zinc-500">{clip.camera_name}</div>
        </div>
      </Card>
    </Link>
  );
}
