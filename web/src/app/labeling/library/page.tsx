'use client';

// /labeling/library — 공용 읽기 전용 영상 보관함(설계 §5.3·§6). 모든 승인 사용자가 모든 카메라의
// 재생 가능한 영상을 탐색한다. 여기서는 라벨을 제출·수정·보류·제외할 수 없다(write control 0).
// 확정 전 라벨은 상태만 노출하고, 기존 라벨은 출처를 명시해 최종 합의 라벨과 구분한다.

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';

import Button from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { ApiError, UnauthorizedError } from '@/lib/labelingApi';
import { createRequestGeneration } from '@/lib/requestGeneration';
import {
  getLabelingLibrary,
  getMotionCamerasSafe,
} from '@/lib/motionBlindReviewApi';
import type { LabelingLibraryItem } from '@/lib/labelingRoleData';
import {
  LibraryCard,
  LibraryFilterControls,
  type LibraryUrlFilters,
} from './_library-views';

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
