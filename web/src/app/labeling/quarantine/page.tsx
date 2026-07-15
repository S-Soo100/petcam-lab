'use client';

// 격리함 목록 (owner 전용) — 검토 필요 / 라벨링 안 함 / 라벨링으로 보냄 3탭 + 촬영일·카메라 필터.
//
// 설계 §4.2, §8.1: owner 가 후보를 빠르게 분류한다. raw evidence·threshold 는 노출하지 않고
// 사전 정의한 한국어 사유(reason_label)만 카드에 보여준다. state/date/camera 는 URL 에 유지해
// 탭 전환·상세 진입·목록 복귀에서 필터가 살아 있다. 접근 게이트는 layout(categorize='owner').

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';

import { createRequestGeneration } from '@/lib/requestGeneration';

import {
  type TriageCameraOption,
  type TriageCounts,
  type TriageListItem,
  type TriageTab,
  ApiError,
  UnauthorizedError,
  getClipThumbnailUrl,
  getTriageCameras,
  getTriagePage,
} from '@/lib/labelingApi';
import Badge from '@/components/ui/Badge';
import Button from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import DateControls from '../_date-controls';

const PAGE_SIZE = 30;

const TABS: { key: TriageTab; label: string }[] = [
  { key: 'pending', label: '검토 필요' },
  { key: 'skipped', label: '라벨링 안 함' },
  { key: 'labeled', label: '라벨링으로 보냄' },
];

interface QuarantineFilters {
  state: TriageTab;
  dateFrom?: string;
  dateTo?: string;
  cameraId?: string;
}

function parseFilters(sp: URLSearchParams): QuarantineFilters {
  const s = sp.get('state');
  return {
    state: s === 'skipped' || s === 'labeled' ? s : 'pending',
    dateFrom: sp.get('date_from') ?? undefined,
    dateTo: sp.get('date_to') ?? undefined,
    cameraId: sp.get('camera_id') ?? undefined,
  };
}

// state/date/camera 를 URL query 로. 상세 링크·목록 복귀가 같은 문자열을 공유한다.
export function buildQuarantineQuery(f: QuarantineFilters): string {
  const p = new URLSearchParams();
  p.set('state', f.state);
  if (f.dateFrom) p.set('date_from', f.dateFrom);
  if (f.dateTo) p.set('date_to', f.dateTo);
  if (f.cameraId) p.set('camera_id', f.cameraId);
  return p.toString();
}

export default function QuarantinePage() {
  return (
    <Suspense
      fallback={
        <main className="mx-auto max-w-4xl px-6 py-8 text-sm text-zinc-500">불러오는 중…</main>
      }
    >
      <QuarantineInner />
    </Suspense>
  );
}

function QuarantineInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const filters = useMemo(
    () => parseFilters(new URLSearchParams(searchParams.toString())),
    [searchParams],
  );
  const tab = filters.state;

  const [items, setItems] = useState<TriageListItem[]>([]);
  const [counts, setCounts] = useState<TriageCounts>({ pending: 0, skipped: 0, labeled: 0 });
  const [cameras, setCameras] = useState<TriageCameraOption[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [loadedOnce, setLoadedOnce] = useState(false);
  // 요청 세대 guard — 필터 변경/새 load 시 세대를 올려 이전 응답(늦은 더보기 포함)을 무시한다.
  const loadGen = useRef(createRequestGeneration());

  const load = useCallback(
    async (nextCursor: string | null) => {
      const gen = loadGen.current.next();
      setBusy(true);
      setErr(null);
      try {
        const resp = await getTriagePage({
          state: tab,
          cursor: nextCursor ?? undefined,
          limit: PAGE_SIZE,
          dateFrom: filters.dateFrom,
          dateTo: filters.dateTo,
          cameraId: filters.cameraId,
        });
        if (!loadGen.current.isCurrent(gen)) return; // stale → 새 필터 목록에 append 금지
        setItems((prev) => (nextCursor ? [...prev, ...resp.items] : resp.items));
        setCounts(resp.counts);
        setCursor(resp.next_cursor);
        setHasMore(resp.has_more);
      } catch (e) {
        if (e instanceof UnauthorizedError) {
          router.replace('/labeling/login');
          return;
        }
        if (!loadGen.current.isCurrent(gen)) return;
        setErr(e instanceof ApiError ? e.message : (e as Error).message);
      } finally {
        if (loadGen.current.isCurrent(gen)) {
          setBusy(false);
          setLoadedOnce(true);
        }
      }
    },
    [router, tab, filters.dateFrom, filters.dateTo, filters.cameraId],
  );

  useEffect(() => {
    load(null);
  }, [load]);

  // 카메라 옵션은 triage 대상 카메라만(owner-only). 실패해도 나머지 필터는 동작.
  useEffect(() => {
    let alive = true;
    getTriageCameras()
      .then((r) => {
        if (alive) setCameras(r.cameras);
      })
      .catch(() => {
        if (alive) setCameras([]);
      });
    return () => {
      alive = false;
    };
  }, []);

  const applyFilters = (next: QuarantineFilters) => {
    router.replace(`/labeling/quarantine?${buildQuarantineQuery(next)}`);
  };

  return (
    <main className="mx-auto max-w-4xl px-6 py-8 space-y-6">
      <div className="flex items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-zinc-900">라벨링 격리함</h1>
          <p className="text-sm text-zinc-500">
            라벨링 가치가 낮아 보이는 후보를 검토해. 영상은 삭제되지 않고 언제든 되돌릴 수 있어.
          </p>
        </div>
        <Button variant="secondary" size="sm" onClick={() => load(null)} disabled={busy}>
          {busy ? '불러오는 중…' : '↻ 새로고침'}
        </Button>
      </div>

      <nav className="flex gap-1 text-sm">
        {TABS.map(({ key, label }) => (
          <button
            key={key}
            type="button"
            onClick={() => applyFilters({ ...filters, state: key })}
            className={`rounded-md px-3 py-1.5 transition-colors ${
              key === tab
                ? 'bg-zinc-900 text-white'
                : 'text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900'
            }`}
          >
            {label} ({counts[key]})
          </button>
        ))}
      </nav>

      <div className="flex flex-wrap items-center gap-2">
        <DateControls
          value={{ date_from: filters.dateFrom, date_to: filters.dateTo }}
          onChange={(range) =>
            applyFilters({ ...filters, dateFrom: range.date_from, dateTo: range.date_to })
          }
        />
        <select
          className="rounded-md border border-zinc-300 bg-white px-2 py-1 text-sm text-zinc-700"
          value={filters.cameraId ?? ''}
          onChange={(e) => applyFilters({ ...filters, cameraId: e.target.value || undefined })}
        >
          <option value="">전체 카메라</option>
          {cameras.map((c) => (
            <option key={c.camera_id} value={c.camera_id}>
              {c.name}
            </option>
          ))}
        </select>
      </div>

      {err && (
        <div className="rounded-md bg-red-50 px-4 py-3 text-sm text-red-700 ring-1 ring-inset ring-red-200">
          {err}
        </div>
      )}

      {loadedOnce && items.length === 0 && !busy && !err && (
        <Card padding="lg">
          <p className="text-sm text-zinc-600">이 조건에 맞는 영상이 없어.</p>
        </Card>
      )}

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {items.map((item) => (
          <TriageCard key={item.clip_id} item={item} filters={filters} />
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

function TriageCard({ item, filters }: { item: TriageListItem; filters: QuarantineFilters }) {
  const [thumbUrl, setThumbUrl] = useState<string | null>(null);
  const [thumbFailed, setThumbFailed] = useState(false);
  const startedAt = item.started_at
    ? new Date(item.started_at).toLocaleString('ko-KR', { timeZone: 'Asia/Seoul', hour12: false })
    : '촬영시각 미상';
  const dur = item.duration_sec ? `${Math.round(item.duration_sec)}s` : '?';

  useEffect(() => {
    let alive = true;
    getClipThumbnailUrl(item.clip_id)
      .then((r) => {
        if (alive) setThumbUrl(r.url);
      })
      .catch(() => {
        if (alive) setThumbFailed(true);
      });
    return () => {
      alive = false;
    };
  }, [item.clip_id]);

  const showThumb = Boolean(thumbUrl) && !thumbFailed;
  const href = `/labeling/quarantine/${item.clip_id}?${buildQuarantineQuery(filters)}`;

  return (
    <Link href={href} prefetch={false}>
      <Card className="cursor-pointer transition-shadow hover:shadow-md">
        <div className="flex items-start gap-3">
          <div className="relative grid h-16 w-24 flex-shrink-0 place-items-center overflow-hidden rounded-md bg-zinc-100 text-xs text-zinc-500">
            {showThumb ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={thumbUrl as string}
                alt=""
                loading="lazy"
                onError={() => setThumbFailed(true)}
                className="h-full w-full object-cover"
              />
            ) : thumbFailed ? (
              <span className="text-red-600">썸네일 실패</span>
            ) : (
              '불러오는 중'
            )}
          </div>
          <div className="min-w-0 flex-1 space-y-1">
            <div className="flex flex-wrap items-center gap-1.5">
              <Badge tone="warning">{item.reason_label}</Badge>
              <span className="text-xs text-zinc-500">{dur}</span>
            </div>
            <div className="text-sm font-medium tabular-nums text-zinc-800">{startedAt}</div>
            <div className="truncate text-xs text-zinc-500" title={item.camera_id ?? ''}>
              카메라 {item.camera_id ?? '미상'}
            </div>
          </div>
        </div>
      </Card>
    </Link>
  );
}
