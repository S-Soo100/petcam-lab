'use client';

// 라벨링 큐 — 본인이 아직 라벨 안 한 클립 목록.
//
// 백엔드 GET /labels/queue:
// - labelers 멤버: 모든 user_id 클립 (전체 클립 풀에서 본인 라벨한 거 빼고)
// - 비-라벨러 (owner): 본인 user_id 클립만
// - seek pagination: started_at desc, cursor 는 마지막 row 의 started_at
//
// UX:
// - 카드 클릭 → /labeling/{clipId}
// - 더보기 버튼: cursor 로 다음 페이지
// - 빈 상태: 라벨 다 했거나 큐가 비어있음 표시

import { Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';

import {
  type ClipRow,
  type QueueResponse,
  ApiError,
  UnauthorizedError,
  getClipThumbnailUrl,
  getQueue,
} from '@/lib/labelingApi';
import Badge from '@/components/ui/Badge';
import Button from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import FilterBar, { type FilterState } from './_filter-bar';
import DateControls from './_date-controls';

const PAGE_SIZE = 30;

// Blind GT 큐에서는 VLM 유무/판정을 필터에도 노출하지 않는다.
function parseQueueFilters(sp: URLSearchParams): FilterState {
  const csv = (k: string) => {
    const v = sp.get(k);
    return v ? v.split(',') : undefined;
  };
  return {
    camera_id: csv('camera_id'),
    date_from: sp.get('date_from') ?? undefined,
    date_to: sp.get('date_to') ?? undefined,
  };
}

function queueFiltersToQuery(f: FilterState): string {
  const p = new URLSearchParams();
  if (f.camera_id?.length) p.set('camera_id', f.camera_id.join(','));
  if (f.date_from) p.set('date_from', f.date_from);
  if (f.date_to) p.set('date_to', f.date_to);
  return p.toString();
}

// useSearchParams 는 Suspense 경계가 필요 (Next.js prerender) → wrapper 분리.
export default function LabelingQueuePage() {
  return (
    <Suspense
      fallback={
        <main className="mx-auto max-w-4xl px-6 py-8 text-sm text-zinc-500">
          불러오는 중…
        </main>
      }
    >
      <QueueInner />
    </Suspense>
  );
}

function QueueInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  // URL → 필터 (새로고침/공유 시 유지). searchParams 바뀔 때만 재계산.
  const filters = useMemo(
    () => parseQueueFilters(new URLSearchParams(searchParams.toString())),
    [searchParams],
  );

  const [items, setItems] = useState<ClipRow[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [loadedOnce, setLoadedOnce] = useState(false);

  const load = useCallback(
    async (nextCursor: string | null) => {
      setBusy(true);
      setErr(null);
      try {
        // 필터는 cursor 페이지네이션에도 항상 함께 전달.
        const resp: QueueResponse = await getQueue({
          limit: PAGE_SIZE,
          cursor: nextCursor ?? undefined,
          filters,
        });
        setItems((prev) => (nextCursor ? [...prev, ...resp.items] : resp.items));
        setCursor(resp.next_cursor);
        setHasMore(resp.has_more);
      } catch (e) {
        if (e instanceof UnauthorizedError) {
          router.replace('/labeling/login');
          return;
        }
        setErr(e instanceof ApiError ? e.message : (e as Error).message);
      } finally {
        setBusy(false);
        setLoadedOnce(true);
      }
    },
    [router, filters], // 필터 바뀌면 load 재생성 → 첫 페이지부터 재로드
  );

  useEffect(() => {
    load(null);
  }, [load]);

  // 필터 변경 → URL 갱신 (searchParams 변경 → filters 재계산 → 재로드)
  const applyFilters = (next: FilterState) => {
    const qs = queueFiltersToQuery(next);
    router.replace(qs ? `/labeling?${qs}` : '/labeling');
  };

  return (
    <main className="mx-auto max-w-4xl px-6 py-8 space-y-6">
      <div className="flex items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-zinc-900">
            라벨 대기 큐
          </h1>
          <p className="text-sm text-zinc-500">
            본인이 라벨 안 한 클립 (최신순). 클릭 → 단건 라벨링.
          </p>
        </div>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => load(null)}
          disabled={busy}
        >
          {busy ? '불러오는 중…' : '↻ 새로고침'}
        </Button>
      </div>

      <DateControls
        value={{ date_from: filters.date_from, date_to: filters.date_to }}
        onChange={(range) =>
          applyFilters({
            ...filters,
            date_from: range.date_from,
            date_to: range.date_to,
          })
        }
      />

      <FilterBar
        axes={{ camera: true }}
        value={filters}
        onChange={applyFilters}
      />

      {err && (
        <div className="rounded-md bg-red-50 px-4 py-3 text-sm text-red-700 ring-1 ring-inset ring-red-200">
          {err}
        </div>
      )}

      {loadedOnce && items.length === 0 && !busy && !err && (
        <Card padding="lg">
          <p className="text-sm text-zinc-600">
            라벨할 클립이 없어요. 캡처 워커가 새 클립을 만들면 여기 뜹니다.
          </p>
        </Card>
      )}

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {items.map((clip) => (
          <ClipCard key={clip.id} clip={clip} />
        ))}
      </div>

      {hasMore && (
        <div className="flex justify-center pt-2">
          <Button
            variant="secondary"
            onClick={() => load(cursor)}
            disabled={busy}
          >
            {busy ? '불러오는 중…' : '더보기'}
          </Button>
        </div>
      )}
    </main>
  );
}

function ClipCard({ clip }: { clip: ClipRow }) {
  const [thumbUrl, setThumbUrl] = useState<string | null>(null);
  const [thumbFailed, setThumbFailed] = useState(false);
  const startedAt = new Date(clip.started_at).toLocaleString('ko-KR', {
    timeZone: 'Asia/Seoul',
    hour12: false,
  });
  const dur = clip.duration_sec ? `${Math.round(clip.duration_sec)}s` : '?';

  // 썸네일은 same-origin route에서 발급. 실패를 숨기지 않고 재시도 상태로 표시한다.
  useEffect(() => {
    let alive = true;
    getClipThumbnailUrl(clip.id)
      .then((r) => {
        if (alive) setThumbUrl(r.url);
      })
      .catch(() => {
        if (alive) setThumbFailed(true);
      });
    return () => {
      alive = false;
    };
  }, [clip.id]);

  const showThumb = Boolean(thumbUrl) && !thumbFailed;

  return (
    <Link href={`/labeling/${clip.id}`} prefetch={false}>
      <Card className="cursor-pointer transition-shadow hover:shadow-md">
        <div className="flex items-start gap-3">
          <div className="relative grid h-16 w-24 flex-shrink-0 place-items-center overflow-hidden rounded-md bg-zinc-100 text-xs text-zinc-500">
            {showThumb ? (
              // R2 signed URL 은 외부 도메인 + 단기 TTL 이라 next/image 최적화와
              // 안 맞음. 라벨링 내부 툴이라 native img + lazy 로 충분.
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={thumbUrl as string}
                alt=""
                loading="lazy"
                onError={() => setThumbFailed(true)}
                className="h-full w-full object-cover"
              />
            ) : thumbFailed ? (
              <button
                type="button"
                className="text-red-600 underline"
                onClick={(event) => {
                  event.preventDefault();
                  event.stopPropagation();
                  setThumbFailed(false);
                  getClipThumbnailUrl(clip.id)
                    .then((result) => setThumbUrl(result.url))
                    .catch(() => setThumbFailed(true));
                }}
              >
                재시도
              </button>
            ) : clip.r2_key ? (
              '불러오는 중'
            ) : (
              '미동기'
            )}
          </div>
          <div className="min-w-0 flex-1 space-y-1">
            <div className="flex flex-wrap items-center gap-1.5">
              {clip.has_motion ? (
                <Badge tone="success">모션</Badge>
              ) : (
                <Badge tone="neutral">정지</Badge>
              )}
              {clip.session_stage === 'gt_locked' && (
                <Badge tone="warning">VLM 검수 이어하기</Badge>
              )}
              <span className="text-xs text-zinc-500">{dur}</span>
            </div>
            <div className="text-sm font-medium tabular-nums text-zinc-800">
              {startedAt}
            </div>
            <div className="truncate text-xs text-zinc-500" title={clip.id}>
              {clip.id}
            </div>
          </div>
        </div>
      </Card>
    </Link>
  );
}
