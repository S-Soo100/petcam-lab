'use client';

// 큐/내라벨 공통 필터 바.
//
// - axes 로 어느 축을 노출할지 탭이 결정 (큐: 카메라/VLM판정/유무/날짜,
//   내라벨: 카메라/라벨/lick_target/날짜).
// - MVP 는 축당 단일 선택(select). 백엔드는 comma 다중을 지원하므로 나중에
//   multi-select 로 확장해도 여기(FilterState 배열)만 바꾸면 됨.
// - 값/onChange 는 부모가 URL querystring 과 동기화 (page.tsx / me/page.tsx).

import { useEffect, useState } from 'react';

import { getFilterOptions, type CameraOption } from '@/lib/labelingApi';
import Button from '@/components/ui/Button';

// 노출 축 — 큐/내라벨이 서로 다른 조합을 씀.
export interface FilterAxes {
  camera?: boolean;
  vlmAction?: boolean; // 큐 전용
  hasVlm?: boolean; // 큐 전용
  action?: boolean; // 내라벨 전용
  lickTarget?: boolean; // 내라벨 전용
  date?: boolean;
}

// 두 탭 공통 값 컨테이너 — 안 쓰는 축은 undefined. getQueue/getMyLabeled
// filters 로 그대로 넘어감(구조적 타이핑 — 각 함수는 자기 축만 읽음).
export interface FilterState {
  camera_id?: string[];
  vlm_action?: string[];
  has_vlm?: boolean;
  action?: string[];
  lick_target?: string[];
  date_from?: string;
  date_to?: string;
}

// labelingApi ActionType / LickTargetType 와 정합 유지.
const ACTIONS = [
  'eating_paste',
  'drinking',
  'moving',
  'unknown',
  'eating_prey',
  'defecating',
  'shedding',
  'basking',
  'unseen',
  'hand_feeding',
];
const LICK_TARGETS = ['air', 'dish', 'floor', 'wall', 'object', 'other'];

const SEL =
  'rounded-md border border-zinc-300 bg-white px-2 py-1 text-sm text-zinc-700';

export default function FilterBar({
  axes,
  value,
  onChange,
}: {
  axes: FilterAxes;
  value: FilterState;
  onChange: (next: FilterState) => void;
}) {
  const [cameras, setCameras] = useState<CameraOption[]>([]);

  useEffect(() => {
    if (!axes.camera) return;
    let alive = true;
    getFilterOptions()
      .then((o) => {
        if (alive) setCameras(o.cameras);
      })
      .catch(() => {
        // 옵션 로드 실패(엔드포인트 미구현 등)해도 나머지 필터는 동작 —
        // 카메라 드롭다운만 비어 있게 둔다.
        if (alive) setCameras([]);
      });
    return () => {
      alive = false;
    };
  }, [axes.camera]);

  // MVP 단일 선택 → 배열(0/1개)로 정규화.
  const one = (v?: string[]) => (v && v.length ? v[0] : '');
  const setOne = (key: keyof FilterState, v: string) =>
    onChange({ ...value, [key]: v ? [v] : undefined });

  const hasAny = Boolean(
    value.camera_id?.length ||
      value.vlm_action?.length ||
      value.action?.length ||
      value.lick_target?.length ||
      value.has_vlm !== undefined ||
      value.date_from ||
      value.date_to,
  );

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-md bg-zinc-50 px-3 py-2 ring-1 ring-inset ring-zinc-200">
      {axes.camera && (
        <select
          className={SEL}
          value={one(value.camera_id)}
          onChange={(e) => setOne('camera_id', e.target.value)}
        >
          <option value="">전체 카메라</option>
          {cameras.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
      )}

      {axes.vlmAction && (
        <select
          className={SEL}
          value={one(value.vlm_action)}
          onChange={(e) => setOne('vlm_action', e.target.value)}
        >
          <option value="">전체 VLM 판정</option>
          {ACTIONS.map((a) => (
            <option key={a} value={a}>
              🔍 {a}
            </option>
          ))}
        </select>
      )}

      {axes.hasVlm && (
        <select
          className={SEL}
          value={value.has_vlm === undefined ? '' : String(value.has_vlm)}
          onChange={(e) =>
            onChange({
              ...value,
              has_vlm:
                e.target.value === '' ? undefined : e.target.value === 'true',
            })
          }
        >
          <option value="">분석 유무 전체</option>
          <option value="true">분석됨</option>
          <option value="false">미분석</option>
        </select>
      )}

      {axes.action && (
        <select
          className={SEL}
          value={one(value.action)}
          onChange={(e) => setOne('action', e.target.value)}
        >
          <option value="">전체 라벨</option>
          {ACTIONS.map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </select>
      )}

      {axes.lickTarget && (
        <select
          className={SEL}
          value={one(value.lick_target)}
          onChange={(e) => setOne('lick_target', e.target.value)}
        >
          <option value="">전체 lick_target</option>
          {LICK_TARGETS.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      )}

      {axes.date && (
        <>
          <input
            type="date"
            className={SEL}
            value={value.date_from?.slice(0, 10) ?? ''}
            onChange={(e) =>
              onChange({
                ...value,
                date_from: e.target.value
                  ? `${e.target.value}T00:00:00+09:00`
                  : undefined,
              })
            }
          />
          <span className="text-xs text-zinc-400">~</span>
          <input
            type="date"
            className={SEL}
            value={value.date_to?.slice(0, 10) ?? ''}
            onChange={(e) =>
              onChange({
                ...value,
                date_to: e.target.value
                  ? `${e.target.value}T23:59:59+09:00`
                  : undefined,
              })
            }
          />
        </>
      )}

      {hasAny && (
        <Button variant="secondary" size="sm" onClick={() => onChange({})}>
          필터 초기화
        </Button>
      )}
    </div>
  );
}
