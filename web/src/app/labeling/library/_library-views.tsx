'use client';

import Link from 'next/link';

import Badge from '@/components/ui/Badge';
import { formatClipCapturedAt } from '@/lib/labelingV2';
import type { LabelingLibraryFilters } from '@/lib/motionBlindReviewApi';
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
