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

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';

import {
  type ClipRow,
  type QueueResponse,
  ApiError,
  UnauthorizedError,
  getQueue,
} from '@/lib/labelingApi';
import Badge from '@/components/ui/Badge';
import Button from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';

const PAGE_SIZE = 30;

export default function LabelingQueuePage() {
  const router = useRouter();
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
        const opts: { limit: number; cursor?: string } = { limit: PAGE_SIZE };
        if (nextCursor) opts.cursor = nextCursor;
        const resp: QueueResponse = await getQueue(opts);
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
    [router],
  );

  useEffect(() => {
    load(null);
  }, [load]);

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
  const startedAt = new Date(clip.started_at).toLocaleString('ko-KR', {
    timeZone: 'Asia/Seoul',
    hour12: false,
  });
  const dur = clip.duration_sec ? `${Math.round(clip.duration_sec)}s` : '?';

  return (
    <Link href={`/labeling/${clip.id}`} prefetch={false}>
      <Card className="cursor-pointer transition-shadow hover:shadow-md">
        <div className="flex items-start gap-3">
          <div className="grid h-16 w-24 flex-shrink-0 place-items-center rounded-md bg-zinc-100 text-xs text-zinc-500">
            {clip.r2_key ? '영상' : '미동기'}
          </div>
          <div className="min-w-0 flex-1 space-y-1">
            <div className="flex items-center gap-1.5">
              {clip.has_motion ? (
                <Badge tone="success">모션</Badge>
              ) : (
                <Badge tone="neutral">정지</Badge>
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
