'use client';

// 라벨링 v4 목록 — A(내 카메라, scope=mine)·B(전체, scope=all) 공용(v4 스펙 §2 In 3·4, §5).
// 행마다 규칙 1차 판정(하이라이트 O/X)·근거·라벨 상태를 카드로 보여주고 상세(/labeling/v4/<id>)로 간다.
// 필터는 URL 쿼리가 SOT(뒤로가기·공유 가능). 기본 필터는 '라벨 안 됨'이고, 모든 상태를 보려면
// `?all=1` 로 명시한다. 카메라 배정은 편의 필터일 뿐 권한이 아니다(§4.1) — mine 은 배정 카메라만 칩으로.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';

import Badge from '@/components/ui/Badge';
import Button from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { SelectionChip } from '@/components/ui/SelectionControl';
import { ApiError, UnauthorizedError } from '@/lib/labelingApi';
import { formatClipCapturedAt } from '@/lib/labelingV2';
import {
  V4_BEHAVIOR_FLAG_LABEL,
  V4_HIGHLIGHT_STATE_LABELS,
  V4_LABEL_STATE_LABELS,
  behaviorGtPath,
  v4DetailPath,
  type V4BehaviorFlagFilter,
  type V4CameraOption,
  type V4ClipItem,
  type V4HighlightState,
  type V4LabelState,
  type V4Scope,
} from '@/lib/labelingV4';
import { getV4Cameras, getV4Clips } from '@/lib/labelingV4Api';
import { createRequestGeneration } from '@/lib/requestGeneration';

const PAGE_SIZE = 30;

export function highlightBadge(h: V4ClipItem['highlight']) {
  if (h.status === 'pending') return <Badge tone="neutral">분석 대기</Badge>;
  if (h.status === 'failed') return <Badge tone="warning">분석 실패</Badge>;
  return <Badge tone={h.value ? 'success' : 'neutral'}>{h.value ? '하이라이트 O' : '하이라이트 X'}</Badge>;
}

// 순수 카드(SSR 테스트 대상). reviewer UUID·run id 는 타입에 없다.
// gtHref: 체크된 영상에서 기존 행동 GT 라벨링으로 가는 링크(승인 사용자 모두). 카드 Link 안에 anchor 를
// 중첩할 수 없어 카드 아래 별도 줄로 그린다.
export function V4ClipCard({ item, gtHref = null }: { item: V4ClipItem; gtHref?: string | null }) {
  const h = item.highlight;
  const showGt = Boolean(gtHref) && item.behavior_flag.flagged;
  return (
    <div className="space-y-1">
    <Link href={v4DetailPath(item.id)} prefetch={false} className="block">
      <Card className="space-y-2 hover:bg-zinc-50">
        <div className="flex flex-wrap items-center gap-2">
          {highlightBadge(h)}
          {item.behavior_flag.flagged && <Badge tone="warning">✨ {V4_BEHAVIOR_FLAG_LABEL}</Badge>}
          <span className="text-sm font-medium text-zinc-900">{item.camera_name}</span>
          <span className="text-xs text-zinc-500">{formatClipCapturedAt(item.started_at, item.duration_sec)}</span>
        </div>
        <p className="text-xs text-zinc-600">{h.reason}</p>
        <p className="text-xs">
          {h.source === 'human' ? (
            <span className="text-emerald-800">{h.reviewer_name ?? '라벨러'}님 확정</span>
          ) : (
            <span className="text-amber-800">라벨 안 됨</span>
          )}
          {!item.media_ready && <span className="ml-2 text-rose-700">재생 불가</span>}
        </p>
      </Card>
    </Link>
    {showGt && (
      <Link href={gtHref as string} prefetch={false} className="inline-block px-1 text-xs text-amber-800 underline">
        행동 라벨링 열기 →
      </Link>
    )}
    </div>
  );
}

export interface UrlFilters {
  cameraIds: string[];
  labelState: V4LabelState | null;
  highlightState: V4HighlightState | null;
  behaviorFlag: V4BehaviorFlagFilter | null;
}

// URL → 필터(순수). label_state 미지정 + all 미지정이면 기본 '라벨 안 됨'(applyDefaultLabelState).
export function readFilters(sp: URLSearchParams): UrlFilters {
  const ls = sp.get('label_state');
  const hs = sp.get('highlight_state');
  return {
    cameraIds: sp.getAll('camera_id'),
    labelState: ls === 'unlabeled' || ls === 'labeled' ? ls : null,
    highlightState: hs === 'yes' || hs === 'no' || hs === 'pending' ? hs : null,
    behaviorFlag: sp.get('behavior_flag') === 'yes' ? 'yes' : null,
  };
}

export function applyDefaultLabelState(sp: URLSearchParams, f: UrlFilters): UrlFilters {
  return !sp.has('label_state') && !sp.has('all') ? { ...f, labelState: 'unlabeled' } : f;
}

// 필터 → 쿼리(순수). labelState 가 null 이면 다른 필터가 있어도 항상 `all=1` 을 남겨
// 기본값('라벨 안 됨')이 되살아나지 않게 한다(카메라·하이라이트 필터만 있을 때 라벨 필터 해제가 안 되던 버그).
export function writeFilters(f: UrlFilters): string {
  const sp = new URLSearchParams();
  f.cameraIds.forEach((id) => sp.append('camera_id', id));
  if (f.labelState) sp.set('label_state', f.labelState);
  else sp.set('all', '1');
  if (f.highlightState) sp.set('highlight_state', f.highlightState);
  if (f.behaviorFlag) sp.set('behavior_flag', f.behaviorFlag);
  return sp.toString();
}

// A(scope=mine)·B(scope=all) 공용. 기본 필터는 '라벨 안 됨'(스펙 §5).
export default function V4ClipList({ scope, basePath, title }: { scope: V4Scope; basePath: string; title: string }) {
  const router = useRouter();
  const sp = useSearchParams();
  const filters = useMemo(() => applyDefaultLabelState(sp, readFilters(sp)), [sp]);
  const [items, setItems] = useState<V4ClipItem[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [cameras, setCameras] = useState<V4CameraOption[]>([]);
  // 필터가 빠르게 바뀔 때 늦게 도착한 이전 응답이 화면을 덮지 않도록 세대 번호로 가드한다.
  const gen = useRef(createRequestGeneration());

  useEffect(() => {
    getV4Cameras().then(setCameras).catch(() => setCameras([]));
  }, []);

  const load = useCallback(
    async (next: string | null) => {
      const g = gen.current.next();
      setBusy(true);
      setErr(null);
      try {
        const resp = await getV4Clips({
          scope,
          cameraIds: filters.cameraIds,
          labelState: filters.labelState,
          highlightState: filters.highlightState,
          behaviorFlag: filters.behaviorFlag,
          cursor: next ?? undefined,
          limit: PAGE_SIZE,
        });
        if (!gen.current.isCurrent(g)) return;
        setItems((prev) => (next ? [...prev, ...resp.items] : resp.items));
        setCursor(resp.next_cursor);
        setHasMore(resp.has_more);
      } catch (cause) {
        if (!gen.current.isCurrent(g)) return;
        if (cause instanceof UnauthorizedError) {
          router.replace('/labeling/login');
          return;
        }
        setErr(cause instanceof ApiError ? cause.message : (cause as Error).message);
      } finally {
        if (gen.current.isCurrent(g)) setBusy(false);
      }
    },
    [scope, filters, router],
  );

  useEffect(() => {
    void load(null);
  }, [load]);

  const update = (patch: Partial<UrlFilters>) => {
    router.replace(`${basePath}?${writeFilters({ ...filters, ...patch })}`);
  };

  const visibleCameras = scope === 'mine' ? cameras.filter((c) => c.assigned) : cameras;

  return (
    <main className="min-w-0 space-y-4 px-4 py-6">
      <h1 className="text-xl font-semibold tracking-tight text-zinc-900">{title}</h1>
      <div className="flex flex-wrap gap-2">
        {(['unlabeled', 'labeled'] as const).map((s) => (
          <SelectionChip
            key={s}
            pressed={filters.labelState === s}
            tone="neutral"
            type="button"
            onClick={() => update({ labelState: filters.labelState === s ? null : s })}
          >
            {V4_LABEL_STATE_LABELS[s]}
          </SelectionChip>
        ))}
        {(['yes', 'no', 'pending'] as const).map((s) => (
          <SelectionChip
            key={s}
            pressed={filters.highlightState === s}
            tone="success"
            type="button"
            onClick={() => update({ highlightState: filters.highlightState === s ? null : s })}
          >
            {V4_HIGHLIGHT_STATE_LABELS[s]}
          </SelectionChip>
        ))}
        <SelectionChip
          pressed={filters.behaviorFlag === 'yes'}
          tone="warning"
          type="button"
          onClick={() => update({ behaviorFlag: filters.behaviorFlag === 'yes' ? null : 'yes' })}
        >
          ✨ {V4_BEHAVIOR_FLAG_LABEL}
        </SelectionChip>
      </div>
      {visibleCameras.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {visibleCameras.map((c) => (
            <SelectionChip
              key={c.id}
              pressed={filters.cameraIds.includes(c.id)}
              tone="neutral"
              type="button"
              onClick={() =>
                update({
                  cameraIds: filters.cameraIds.includes(c.id)
                    ? filters.cameraIds.filter((x) => x !== c.id)
                    : [...filters.cameraIds, c.id],
                })
              }
            >
              {c.name}
            </SelectionChip>
          ))}
        </div>
      )}
      {scope === 'mine' && visibleCameras.length === 0 && !busy && (
        <Card className="text-sm text-zinc-600">
          배정된 카메라가 없어. owner 에게 배정을 요청하거나{' '}
          <Link href="/labeling/all" className="underline">
            전체
          </Link>
          에서 라벨링할 수 있어.
        </Card>
      )}
      {err && <Card className="border-rose-200 bg-rose-50 text-sm text-rose-800">{err}</Card>}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {items.map((it) => (
          <V4ClipCard key={it.id} item={it} gtHref={behaviorGtPath(it.id)} />
        ))}
      </div>
      {!busy && items.length === 0 && !err && <p className="text-sm text-zinc-500">조건에 맞는 영상이 없어.</p>}
      {hasMore && (
        <Button variant="secondary" onClick={() => load(cursor)} disabled={busy}>
          {busy ? '불러오는 중…' : '더보기'}
        </Button>
      )}
    </main>
  );
}
