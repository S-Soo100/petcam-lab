'use client';

// 라벨러 '내 기록'(설계 §5.2). 본인이 제출한 immutable 기록만 보여준다. 상대 제출 원문·불일치
// 필드는 노출하지 않고, 최종 합의 상태는 확정됨/검수 중 두 단계로만 표시한다. 기록은 불변이라
// 수정 버튼이 없다. 카드 클릭은 읽기 전용 영상 상세(영상 보관함)로만 이동한다 — 상대 엔드포인트로
// 가지 않는다. keyset 페이지네이션 + stale 응답 폐기(request generation).

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';

import Badge from '@/components/ui/Badge';
import Button from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { ApiError, UnauthorizedError } from '@/lib/labelingApi';
import { createRequestGeneration } from '@/lib/requestGeneration';
import { formatClipCapturedAt } from '@/lib/labelingV2';
import { BLIND_DECISION_COPY } from '@/lib/motionBlindReview';
import {
  getBlindHistory,
  getMotionCamerasSafe,
  type LabelingHistoryFilters,
} from '@/lib/motionBlindReviewApi';
import {
  finalStatusCopy,
  type BlindHistoryItem,
} from '@/lib/labelingRoleData';
import { blindReasonCopy } from './_blind-review-view';

const DECISION_OPTIONS: { value: string; label: string }[] = [
  { value: '', label: '전체 판정' },
  { value: 'label', label: '라벨링' },
  { value: 'hold', label: '보류' },
  { value: 'exclude', label: '제외' },
];

const COHORT_OPTIONS: { value: string; label: string }[] = [
  { value: '', label: '전체' },
  { value: 'live', label: '운영' },
  { value: 'canary', label: '검증' },
];

function parseFilters(sp: URLSearchParams): LabelingHistoryFilters {
  return {
    decision: sp.get('decision') || null,
    cohortKind: (sp.get('cohort_kind') as 'live' | 'canary' | null) || null,
    cameraIds: sp.getAll('camera_id'),
    dateFrom: sp.get('date_from') || null,
    dateTo: sp.get('date_to') || null,
  };
}

function filtersToQuery(f: LabelingHistoryFilters): string {
  const p = new URLSearchParams();
  if (f.decision) p.set('decision', f.decision);
  if (f.cohortKind) p.set('cohort_kind', f.cohortKind);
  (f.cameraIds ?? []).forEach((id) => p.append('camera_id', id));
  if (f.dateFrom) p.set('date_from', f.dateFrom);
  if (f.dateTo) p.set('date_to', f.dateTo);
  return p.toString();
}

export default function LabelerHistory() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const filters = useMemo(
    () => parseFilters(new URLSearchParams(searchParams.toString())),
    [searchParams],
  );

  const [items, setItems] = useState<BlindHistoryItem[]>([]);
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
        const resp = await getBlindHistory({ ...filters, cursor: nextCursor ?? undefined });
        if (!gen.isCurrent(mine)) return; // 필터가 바뀌면 stale 응답 폐기.
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

  const applyFilter = (patch: Partial<LabelingHistoryFilters>) => {
    const next = filtersToQuery({ ...filters, ...patch });
    router.replace(next ? `/labeling/me?${next}` : '/labeling/me');
  };

  return (
    <main className="min-w-0 space-y-4 px-4 py-6">
      <div className="min-w-0">
        <h1 className="whitespace-nowrap text-xl font-semibold tracking-tight text-zinc-900">
          내 기록
        </h1>
        <p className="text-sm text-zinc-500">내가 제출한 라벨만 모아 봐. 제출한 라벨은 수정할 수 없어.</p>
      </div>

      <div className="flex flex-wrap items-end gap-2 text-sm">
        <label className="flex flex-col gap-0.5">
          <span className="text-xs text-zinc-500">판정</span>
          <select
            className="rounded-md border border-zinc-300 px-2 py-1"
            value={filters.decision ?? ''}
            onChange={(e) => applyFilter({ decision: e.target.value || null })}
          >
            {DECISION_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-0.5">
          <span className="text-xs text-zinc-500">코호트</span>
          <select
            className="rounded-md border border-zinc-300 px-2 py-1"
            value={filters.cohortKind ?? ''}
            onChange={(e) =>
              applyFilter({ cohortKind: (e.target.value as 'live' | 'canary') || null })
            }
          >
            {COHORT_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-0.5">
          <span className="text-xs text-zinc-500">카메라</span>
          <select
            className="max-w-[10rem] rounded-md border border-zinc-300 px-2 py-1"
            value={filters.cameraIds?.[0] ?? ''}
            onChange={(e) => applyFilter({ cameraIds: e.target.value ? [e.target.value] : [] })}
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
          <span className="text-xs text-zinc-500">시작</span>
          <input
            type="date"
            className="rounded-md border border-zinc-300 px-2 py-1"
            value={filters.dateFrom ?? ''}
            onChange={(e) => applyFilter({ dateFrom: e.target.value || null })}
          />
        </label>
        <label className="flex flex-col gap-0.5">
          <span className="text-xs text-zinc-500">끝</span>
          <input
            type="date"
            className="rounded-md border border-zinc-300 px-2 py-1"
            value={filters.dateTo ?? ''}
            onChange={(e) => applyFilter({ dateTo: e.target.value || null })}
          />
        </label>
      </div>

      {err && (
        <Card className="border-rose-200 bg-rose-50 text-sm text-rose-800">{err}</Card>
      )}

      {loadedOnce && items.length === 0 && !busy && !err && (
        <Card className="text-sm text-zinc-600">아직 제출한 라벨이 없어.</Card>
      )}

      <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {items.map((item) => (
          <li key={item.submission_id} className="min-w-0">
            <HistoryCard item={item} />
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

// 순수 표시 카드(SSR 테스트 대상). 본인 제출 필드만 렌더하고, 상대 판정·digest·reviewer 는
// 애초에 item 에 없다. 링크는 읽기 전용 영상 상세로만 간다(상대 엔드포인트 X).
export function HistoryCard({ item }: { item: BlindHistoryItem }) {
  const decision = BLIND_DECISION_COPY[item.decision as keyof typeof BLIND_DECISION_COPY];
  const submittedAt = new Date(item.submitted_at).toLocaleString('ko-KR', {
    timeZone: 'Asia/Seoul',
    hour12: false,
  });
  const gtSummary = summarizeGt(item.initial_gt);

  return (
    <Link
      href={`/labeling/library/${item.clip_id}`}
      prefetch={false}
      className="block min-w-0 rounded-xl border border-zinc-200 bg-white p-3 text-sm shadow-sm hover:border-zinc-400"
    >
      <div className="flex items-center justify-between gap-2">
        <span className="min-w-0 truncate font-medium text-zinc-900">
          {item.camera_name ?? '카메라'}
        </span>
        <Badge tone={item.final_status === 'confirmed' ? 'success' : 'info'}>
          {finalStatusCopy(item.final_status)}
        </Badge>
      </div>
      <div className="mt-0.5 text-xs text-zinc-500">
        {formatClipCapturedAt(item.started_at, item.duration_sec)}
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-1.5">
        <Badge tone="info">{decision?.title ?? item.decision}</Badge>
        <span className="text-xs text-zinc-500">{blindReasonCopy(item.reason_code)}</span>
      </div>
      {gtSummary && <div className="mt-1 text-xs text-zinc-700">기록: {gtSummary}</div>}
      {item.note && (
        <div className="mt-1 truncate text-xs text-zinc-600" title={item.note}>
          “{item.note}”
        </div>
      )}
      <div className="mt-1 text-[11px] tabular-nums text-zinc-400">제출 {submittedAt}</div>
    </Link>
  );
}

// GT 요약 — 대표 행동만 짧게. 상대 제출과 무관한 본인 GT 이며, 없으면 null.
function summarizeGt(gt: unknown): string | null {
  if (!gt || typeof gt !== 'object') return null;
  const record = gt as Record<string, unknown>;
  const primary = record.primary_action ?? record.action;
  if (typeof primary === 'string' && primary) return primary;
  return '라벨 있음';
}
