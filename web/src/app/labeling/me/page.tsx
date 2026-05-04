'use client';

// 내 라벨 회고 — 본인이 라벨한 클립 + 라벨 1건씩.
//
// 백엔드 GET /labels/mine:
// - labeled_at desc, seek pagination (cursor = labeled_at ISO8601)
// - queue 와 달리 has_motion / r2_key 필터 없음 — 회고 흐름은 모든 라벨한
//   클립 포함 (영상 재생 불가는 단건 페이지에서 안내).
//
// UX:
// - 큐 페이지와 같은 카드 grid + 라벨 정보 (action / lick_target) 추가 표시
// - 카드 클릭 → /labeling/{clipId} (기존 prefill 동작 그대로 사용 — 수정 가능)
// - 빈 상태: "라벨한 클립이 아직 없어요. '큐' 에서 시작하세요."

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';

import {
  type MineItem,
  type MineResponse,
  ApiError,
  UnauthorizedError,
  getMyLabeled,
} from '@/lib/labelingApi';
import Badge from '@/components/ui/Badge';
import Button from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';

const PAGE_SIZE = 30;

export default function LabelingMinePage() {
  const router = useRouter();
  const [items, setItems] = useState<MineItem[]>([]);
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
        const resp: MineResponse = await getMyLabeled(opts);
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
            내 라벨
          </h1>
          <p className="text-sm text-zinc-500">
            내가 라벨한 클립 (최신 라벨순). 클릭 → 기존 라벨 prefill 후 수정.
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
            라벨한 클립이 아직 없어요. <Link href="/labeling" className="text-emerald-600 underline">큐</Link> 에서 시작하세요.
          </p>
        </Card>
      )}

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {items.map((it) => (
          <MineCard key={it.label.id} item={it} />
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

function MineCard({ item }: { item: MineItem }) {
  const { clip, label } = item;
  const labeledAt = new Date(label.labeled_at).toLocaleString('ko-KR', {
    timeZone: 'Asia/Seoul',
    hour12: false,
  });
  const dur = clip.duration_sec ? `${Math.round(clip.duration_sec)}s` : '?';
  const actionDisplay = label.lick_target
    ? `${label.action} (${label.lick_target})`
    : label.action;

  return (
    <Link href={`/labeling/${clip.id}`} prefetch={false}>
      <Card className="cursor-pointer transition-shadow hover:shadow-md">
        <div className="flex items-start gap-3">
          <div className="grid h-16 w-24 flex-shrink-0 place-items-center rounded-md bg-zinc-100 text-xs text-zinc-500">
            {clip.r2_key ? '영상' : '미동기'}
          </div>
          <div className="min-w-0 flex-1 space-y-1">
            <div className="flex flex-wrap items-center gap-1.5">
              <Badge tone="info">{actionDisplay}</Badge>
              <span className="text-xs text-zinc-500">{dur}</span>
            </div>
            <div className="text-xs tabular-nums text-zinc-700">
              라벨 시각: {labeledAt}
            </div>
            {label.note && (
              <div className="truncate text-xs text-zinc-600" title={label.note}>
                "{label.note}"
              </div>
            )}
            <div className="truncate text-[10px] text-zinc-400" title={clip.id}>
              {clip.id}
            </div>
          </div>
        </div>
      </Card>
    </Link>
  );
}
