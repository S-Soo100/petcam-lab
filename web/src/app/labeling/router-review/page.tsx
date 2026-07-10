'use client';

import { Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';

import Badge from '@/components/ui/Badge';
import Button from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import {
  ApiError,
  UnauthorizedError,
  type RouterReviewBatch,
  type RouterReviewItem,
  getRouterReviewBatches,
  getRouterReviewItems,
} from '@/lib/labelingApi';

const DEFAULT_BATCH_ID = 'router-eval-v1-20260710';
const GROUPS = [
  { value: '', label: '전체' },
  { value: 'cloud_now_check', label: 'cloud_now' },
  { value: 'cloud_later_all', label: 'cloud_later' },
  { value: 'review_candidate_quantiles', label: 'review_candidate' },
];
const STATUSES = [
  { value: 'unreviewed', label: '미검수' },
  { value: 'all', label: '전체' },
  { value: 'reviewed', label: '완료' },
] as const;

export default function RouterReviewPage() {
  return (
    <Suspense
      fallback={
        <main className="mx-auto max-w-5xl px-6 py-8 text-sm text-zinc-500">
          불러오는 중…
        </main>
      }
    >
      <RouterReviewInner />
    </Suspense>
  );
}

function RouterReviewInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const batchId = searchParams.get('batch_id') || DEFAULT_BATCH_ID;
  const sampleGroup = searchParams.get('sample_group') || '';
  const status = (searchParams.get('status') || 'unreviewed') as
    | 'all'
    | 'reviewed'
    | 'unreviewed';

  const [batches, setBatches] = useState<RouterReviewBatch[]>([]);
  const [items, setItems] = useState<RouterReviewItem[]>([]);
  const [count, setCount] = useState(0);
  const [reviewedCount, setReviewedCount] = useState(0);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const progressPct = count ? Math.round((reviewedCount / count) * 100) : 0;

  const setQuery = useCallback(
    (next: { batch_id?: string; sample_group?: string; status?: string }) => {
      const params = new URLSearchParams({
        batch_id: next.batch_id ?? batchId,
        status: next.status ?? status,
      });
      const group = next.sample_group ?? sampleGroup;
      if (group) params.set('sample_group', group);
      router.replace(`/labeling/router-review?${params.toString()}`);
    },
    [batchId, router, sampleGroup, status],
  );

  const load = useCallback(async () => {
    setBusy(true);
    setErr(null);
    try {
      const [batchResp, itemResp] = await Promise.all([
        getRouterReviewBatches(),
        getRouterReviewItems({
          batch_id: batchId,
          sample_group: sampleGroup || undefined,
          status,
        }),
      ]);
      setBatches(batchResp);
      setItems(itemResp.items);
      setCount(itemResp.count);
      setReviewedCount(itemResp.reviewed_count);
    } catch (e) {
      if (e instanceof UnauthorizedError) {
        router.replace('/labeling/login');
        return;
      }
      setErr(e instanceof ApiError ? e.message : (e as Error).message);
    } finally {
      setBusy(false);
    }
  }, [batchId, router, sampleGroup, status]);

  useEffect(() => {
    load();
  }, [load]);

  const currentBatch = useMemo(
    () => batches.find((batch) => batch.batch_id === batchId),
    [batchId, batches],
  );

  return (
    <main className="mx-auto max-w-5xl px-6 py-8 space-y-5">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-zinc-900">
            라우터 리뷰
          </h1>
          <p className="mt-1 text-sm text-zinc-500">
            행동 GT 저장이 아니라 metadata router 판단 검증용.
          </p>
        </div>
        <Button variant="secondary" size="sm" onClick={load} disabled={busy}>
          {busy ? '불러오는 중…' : '새로고침'}
        </Button>
      </div>

      <Card className="space-y-4">
        <div className="flex flex-wrap items-center gap-3">
          <label className="space-y-1 text-xs font-medium text-zinc-600">
            <span>batch</span>
            <select
              value={batchId}
              onChange={(e) => setQuery({ batch_id: e.target.value })}
              className="block min-w-60 rounded-md border border-zinc-300 bg-white px-2 py-1.5 text-sm text-zinc-900"
            >
              {(batches.length ? batches : [{ batch_id: batchId, count: 0, reviewed_count: 0 }]).map(
                (batch) => (
                  <option key={batch.batch_id} value={batch.batch_id}>
                    {batch.batch_id}
                  </option>
                ),
              )}
            </select>
          </label>

          <label className="space-y-1 text-xs font-medium text-zinc-600">
            <span>group</span>
            <select
              value={sampleGroup}
              onChange={(e) => setQuery({ sample_group: e.target.value })}
              className="block rounded-md border border-zinc-300 bg-white px-2 py-1.5 text-sm text-zinc-900"
            >
              {GROUPS.map((group) => (
                <option key={group.value} value={group.value}>
                  {group.label}
                </option>
              ))}
            </select>
          </label>

          <label className="space-y-1 text-xs font-medium text-zinc-600">
            <span>status</span>
            <select
              value={status}
              onChange={(e) => setQuery({ status: e.target.value })}
              className="block rounded-md border border-zinc-300 bg-white px-2 py-1.5 text-sm text-zinc-900"
            >
              {STATUSES.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>

          <div className="ml-auto min-w-48 space-y-1">
            <div className="flex justify-between text-xs text-zinc-500">
              <span>진행률</span>
              <span>
                {reviewedCount}/{count || currentBatch?.count || 0}
              </span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-zinc-100">
              <div
                className="h-full bg-zinc-900"
                style={{ width: `${progressPct}%` }}
              />
            </div>
          </div>
        </div>
      </Card>

      {err && (
        <div className="rounded-md bg-red-50 px-4 py-3 text-sm text-red-700 ring-1 ring-inset ring-red-200">
          {err}
        </div>
      )}

      <div className="grid gap-3 md:grid-cols-2">
        {items.map((item) => (
          <ReviewCard key={item.id} item={item} batchId={batchId} />
        ))}
      </div>

      {!busy && !err && items.length === 0 && (
        <Card padding="lg">
          <p className="text-sm text-zinc-600">조건에 맞는 리뷰 item이 없어.</p>
        </Card>
      )}
    </main>
  );
}

function ReviewCard({ item, batchId }: { item: RouterReviewItem; batchId: string }) {
  const startedAt = item.started_at
    ? new Date(item.started_at).toLocaleString('ko-KR', {
        timeZone: 'Asia/Seoul',
        hour12: false,
      })
    : '?';
  return (
    <Link
      href={`/labeling/router-review/${item.clip_id}?batch_id=${encodeURIComponent(batchId)}`}
      prefetch={false}
    >
      <Card className="h-full cursor-pointer transition-shadow hover:shadow-md">
        <div className="flex items-start justify-between gap-3">
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-1.5">
              <Badge tone={item.route === 'cloud_now' ? 'danger' : item.route === 'cloud_later' ? 'info' : 'warning'}>
                {item.route}
              </Badge>
              <Badge tone={item.label ? 'success' : 'neutral'}>
                {item.label ? '완료' : '미검수'}
              </Badge>
              <Badge tone="neutral">{item.evidence_reliability ?? 'no reliability'}</Badge>
            </div>
            <div className="text-sm font-medium text-zinc-900">{item.reason}</div>
            <div className="text-xs tabular-nums text-zinc-500">{startedAt}</div>
          </div>
          <div className="text-right text-xs tabular-nums text-zinc-500">
            <div>mean {fmt(item.motion_mean)}</div>
            <div>peak {fmt(item.motion_peak)}</div>
            <div>active {fmt(item.active_motion_ratio)}</div>
          </div>
        </div>
      </Card>
    </Link>
  );
}

function fmt(value: number | null): string {
  return value === null ? '-' : value.toFixed(3);
}
