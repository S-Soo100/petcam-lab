'use client';

// /labeling/library — 공용 읽기 전용 영상 보관함(설계 §5.3·§6). 모든 승인 사용자가 모든 카메라의
// 재생 가능한 영상을 탐색한다. 여기서는 라벨을 제출·수정·보류·제외할 수 없다(write control 0).
// 확정 전 라벨은 상태만 노출하고, 기존 라벨은 출처를 명시해 최종 합의 라벨과 구분한다.

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';

import Badge from '@/components/ui/Badge';
import Button from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { ApiError, UnauthorizedError } from '@/lib/labelingApi';
import { createRequestGeneration } from '@/lib/requestGeneration';
import { formatClipCapturedAt } from '@/lib/labelingV2';
import {
  getLabelingLibrary,
  getMotionCamerasSafe,
  type LabelingLibraryFilters,
} from '@/lib/motionBlindReviewApi';
import {
  labelSourceCopy,
  labelStateCopy,
  type LabelingLibraryItem,
  type PublicLabelSource,
  type PublicLabelState,
} from '@/lib/labelingRoleData';

const STATE_OPTIONS: { value: string; label: string }[] = [
  { value: '', label: '전체' },
  { value: 'final', label: '최종 라벨' },
  { value: 'awaiting', label: '라벨 확정 중' },
  { value: 'owner_review', label: 'Owner 검수 중' },
  { value: 're_review', label: '라벨 재검수 중' },
  { value: 'unlabeled', label: '미분류' },
];

const SOURCE_OPTIONS: { value: string; label: string }[] = [
  { value: '', label: '전체' },
  { value: 'blind_consensus', label: '이중 확인 완료' },
  { value: 'owner_legacy', label: '기존 Owner 라벨' },
  { value: 'single_legacy', label: '기존 단일 라벨' },
  { value: 'none', label: '라벨 없음' },
];

const FINAL_LABEL_OPTIONS: { value: string; label: string }[] = [
  { value: '', label: '전체' },
  { value: 'label', label: '라벨링' },
  { value: 'hold', label: '보류' },
  { value: 'exclude', label: '제외' },
];

const STATE_TONE: Record<PublicLabelState, 'success' | 'info' | 'warning' | 'neutral'> = {
  final: 'success',
  awaiting: 'info',
  owner_review: 'warning',
  re_review: 'warning',
  unlabeled: 'neutral',
};

// 기존 라벨과 새 합의 라벨을 시각적으로 구분한다(설계 §6.2).
const SOURCE_TONE: Record<PublicLabelSource, 'primary' | 'neutral' | 'warning'> = {
  blind_consensus: 'primary',
  owner_legacy: 'neutral',
  single_legacy: 'warning',
  none: 'neutral',
};

export interface LibraryUrlFilters extends LabelingLibraryFilters {
  finalDecision?: string | null;
}

function parseUrlFilters(sp: URLSearchParams): LibraryUrlFilters {
  return {
    labelState: sp.get('label_state') || null,
    labelSource: sp.get('label_source') || null,
    cameraIds: sp.getAll('camera_id'),
    dateFrom: sp.get('date_from') || null,
    dateTo: sp.get('date_to') || null,
    timeFrom: sp.get('time_from') || null,
    timeTo: sp.get('time_to') || null,
    finalDecision: sp.get('final_decision') || null,
  };
}

function filtersToQuery(f: LibraryUrlFilters): string {
  const p = new URLSearchParams();
  if (f.labelState) p.set('label_state', f.labelState);
  if (f.labelSource) p.set('label_source', f.labelSource);
  (f.cameraIds ?? []).forEach((id) => p.append('camera_id', id));
  if (f.dateFrom) p.set('date_from', f.dateFrom);
  if (f.dateTo) p.set('date_to', f.dateTo);
  if (f.timeFrom) p.set('time_from', f.timeFrom);
  if (f.timeTo) p.set('time_to', f.timeTo);
  if (f.finalDecision) p.set('final_decision', f.finalDecision);
  return p.toString();
}

// 목록 쿼리를 보존해 상세에서 뒤로 돌아올 때 필터를 유지한다(설계 §11).
function listQuery(f: LibraryUrlFilters): string {
  const q = filtersToQuery(f);
  return q ? `?${q}` : '';
}

export default function LibraryPage() {
  return (
    <Suspense
      fallback={<main className="min-w-0 px-4 py-6 text-sm text-zinc-500">불러오는 중…</main>}
    >
      <LibraryList />
    </Suspense>
  );
}

function LibraryList() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const filters = useMemo(
    () => parseUrlFilters(new URLSearchParams(searchParams.toString())),
    [searchParams],
  );

  const [items, setItems] = useState<LabelingLibraryItem[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [loadedOnce, setLoadedOnce] = useState(false);
  const [cameras, setCameras] = useState<{ id: string; name: string }[]>([]);
  const genRef = useRef(createRequestGeneration());

  useEffect(() => {
    let alive = true;
    getMotionCamerasSafe().then((cams) => {
      if (alive) setCameras(cams);
    });
    return () => {
      alive = false;
    };
  }, []);

  const load = useCallback(
    async (nextCursor: string | null) => {
      const gen = genRef.current;
      const mine = gen.next();
      setBusy(true);
      setErr(null);
      try {
        const resp = await getLabelingLibrary({ ...filters, cursor: nextCursor ?? undefined });
        if (!gen.isCurrent(mine)) return;
        setItems((prev) => (nextCursor ? [...prev, ...resp.items] : resp.items));
        setCursor(resp.next_cursor);
        setHasMore(resp.has_more);
      } catch (e) {
        if (!genRef.current.isCurrent(mine)) return;
        if (e instanceof UnauthorizedError) {
          router.replace('/labeling/login');
          return;
        }
        setErr(e instanceof ApiError ? e.message : (e as Error).message);
      } finally {
        if (genRef.current.isCurrent(mine)) {
          setBusy(false);
          setLoadedOnce(true);
        }
      }
    },
    [filters, router],
  );

  useEffect(() => {
    load(null);
  }, [load]);

  const applyFilter = (patch: Partial<LibraryUrlFilters>) => {
    const q = filtersToQuery({ ...filters, ...patch });
    router.replace(q ? `/labeling/library?${q}` : '/labeling/library');
  };

  // 모든 필터(최종 라벨 포함)는 서버 RPC keyset 으로 전량 반영된다(review-fix P1-2). 로드된
  // 페이지만 좁히던 client-side 필터를 제거해 뒤 페이지 결과 누락·거짓 빈 상태를 없앤다.
  const shown = items;

  const back = listQuery(filters);

  return (
    <main className="min-w-0 space-y-4 px-4 py-6">
      <div className="min-w-0">
        <h1 className="whitespace-nowrap text-xl font-semibold tracking-tight text-zinc-900">
          영상 보기
        </h1>
        <p className="text-sm text-zinc-500">모든 카메라의 재생 가능한 영상을 탐색해. 읽기 전용이야.</p>
      </div>

      <LibraryFilterControls
        value={filters}
        cameras={cameras}
        onChange={applyFilter}
        onReset={() => router.replace('/labeling/library')}
      />

      {err && <Card className="border-rose-200 bg-rose-50 text-sm text-rose-800">{err}</Card>}

      {loadedOnce && shown.length === 0 && !busy && !err && (
        <Card className="space-y-2 text-sm text-zinc-600">
          <p>조건에 맞는 영상이 없어.</p>
          <Button variant="secondary" size="sm" onClick={() => router.replace('/labeling/library')}>
            필터 초기화
          </Button>
        </Card>
      )}

      <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {shown.map((item) => (
          <li key={item.clip_id} className="min-w-0">
            <LibraryCard item={item} backHref={back} />
          </li>
        ))}
      </ul>

      {hasMore && (
        <div className="flex justify-center pt-1">
          <Button variant="secondary" onClick={() => load(cursor)} disabled={busy}>
            {busy ? '불러오는 중…' : '더보기'}
          </Button>
        </div>
      )}
    </main>
  );
}

// 순수 필터 컨트롤(SSR 테스트 대상). 모든 컨트롤에 보이는 <label> 텍스트를 둔다(설계 §9 접근성).
export function LibraryFilterControls({
  value,
  cameras,
  onChange,
  onReset,
}: {
  value: LibraryUrlFilters;
  cameras: { id: string; name: string }[];
  onChange: (patch: Partial<LibraryUrlFilters>) => void;
  onReset: () => void;
}) {
  return (
    <div className="flex flex-wrap items-end gap-2 text-sm">
      <fieldset className="flex flex-col gap-0.5">
        <span className="text-xs text-zinc-500">날짜</span>
        <div className="flex items-center gap-1">
          <input
            type="date"
            aria-label="시작 날짜"
            className="rounded-md border border-zinc-300 px-2 py-1"
            value={value.dateFrom ?? ''}
            onChange={(e) => onChange({ dateFrom: e.target.value || null })}
          />
          <span className="text-zinc-400">~</span>
          <input
            type="date"
            aria-label="끝 날짜"
            className="rounded-md border border-zinc-300 px-2 py-1"
            value={value.dateTo ?? ''}
            onChange={(e) => onChange({ dateTo: e.target.value || null })}
          />
        </div>
      </fieldset>

      <fieldset className="flex flex-col gap-0.5">
        <span className="text-xs text-zinc-500">시간대</span>
        <div className="flex items-center gap-1">
          <input
            type="time"
            aria-label="시작 시각"
            className="rounded-md border border-zinc-300 px-2 py-1"
            value={value.timeFrom ?? ''}
            onChange={(e) => onChange({ timeFrom: e.target.value || null })}
          />
          <span className="text-zinc-400">~</span>
          <input
            type="time"
            aria-label="끝 시각"
            className="rounded-md border border-zinc-300 px-2 py-1"
            value={value.timeTo ?? ''}
            onChange={(e) => onChange({ timeTo: e.target.value || null })}
          />
        </div>
      </fieldset>

      <label className="flex flex-col gap-0.5">
        <span className="text-xs text-zinc-500">카메라</span>
        <select
          className="max-w-[10rem] rounded-md border border-zinc-300 px-2 py-1"
          value={value.cameraIds?.[0] ?? ''}
          onChange={(e) => onChange({ cameraIds: e.target.value ? [e.target.value] : [] })}
        >
          <option value="">전체 카메라</option>
          {cameras.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
      </label>

      <label className="flex flex-col gap-0.5">
        <span className="text-xs text-zinc-500">최종 라벨</span>
        <select
          className="rounded-md border border-zinc-300 px-2 py-1"
          value={value.finalDecision ?? ''}
          onChange={(e) => onChange({ finalDecision: e.target.value || null })}
        >
          {FINAL_LABEL_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </label>

      <label className="flex flex-col gap-0.5">
        <span className="text-xs text-zinc-500">라벨 상태</span>
        <select
          className="rounded-md border border-zinc-300 px-2 py-1"
          value={value.labelState ?? ''}
          onChange={(e) => onChange({ labelState: e.target.value || null })}
        >
          {STATE_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </label>

      <label className="flex flex-col gap-0.5">
        <span className="text-xs text-zinc-500">라벨 출처</span>
        <select
          className="rounded-md border border-zinc-300 px-2 py-1"
          value={value.labelSource ?? ''}
          onChange={(e) => onChange({ labelSource: e.target.value || null })}
        >
          {SOURCE_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </label>

      <button
        type="button"
        onClick={onReset}
        className="rounded-md border border-zinc-300 px-2 py-1 text-xs text-zinc-600 hover:bg-zinc-100"
      >
        초기화
      </button>
    </div>
  );
}

// 순수 카드(SSR 테스트 대상). 상태·출처 배지만 노출하고, 확정 전(awaiting/owner_review) 카드는
// GT 필드를 보여주지 않는다(설계 §6.1). write control 없음 — 링크는 읽기 전용 상세로만.
export function LibraryCard({
  item,
  backHref,
}: {
  item: LabelingLibraryItem;
  backHref?: string;
}) {
  const href = `/labeling/library/${item.clip_id}${backHref ? `?back=${encodeURIComponent(backHref)}` : ''}`;
  return (
    <Link
      href={href}
      prefetch={false}
      className="block min-w-0 rounded-xl border border-zinc-200 bg-white p-3 text-sm shadow-sm hover:border-zinc-400"
    >
      <div className="min-w-0 truncate font-medium text-zinc-900">{item.camera_name ?? '카메라'}</div>
      <div className="mt-0.5 text-xs text-zinc-500">
        {formatClipCapturedAt(item.started_at, item.duration_sec)}
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-1.5">
        <Badge tone={STATE_TONE[item.label_state]}>{labelStateCopy(item.label_state)}</Badge>
        <Badge tone={SOURCE_TONE[item.label_source]}>{labelSourceCopy(item.label_source)}</Badge>
        {item.label_state === 'final' && item.final_decision && (
          <span className="text-xs text-zinc-500">최종: {item.final_decision}</span>
        )}
      </div>
    </Link>
  );
}
