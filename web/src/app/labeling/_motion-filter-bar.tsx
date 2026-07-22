'use client';

// motion 큐 v3 필터 바 — 카메라(멀티) + 미디어 + 날짜만(설계 §8.1).
// 카메라 옵션은 v3 전용 getMotionCameras 로 받는다(legacy /labels/filter-options 미사용).

import { useEffect, useState } from 'react';

import type { MotionCameraOption } from '@/lib/labelingV3';
import { getMotionCameras } from '@/lib/labelingV3Api';
import type { MotionQueueUiFilters } from '@/lib/labelingV3QueueClient';
import DateControls from './_date-controls';

const MEDIA_OPTIONS: readonly { value: '' | 'ready' | 'unavailable'; label: string }[] = [
  { value: '', label: '전체' },
  { value: 'ready', label: '재생 가능' },
  { value: 'unavailable', label: '재생 불가' },
];

function chipClass(active: boolean): string {
  return `rounded-md px-2 py-0.5 text-xs ring-1 ring-inset ${
    active
      ? 'bg-zinc-900 text-white ring-zinc-900'
      : 'text-zinc-600 ring-zinc-200 hover:bg-zinc-50'
  }`;
}

export default function MotionFilterBar({
  value,
  onChange,
  showMedia,
}: {
  value: MotionQueueUiFilters;
  onChange: (next: MotionQueueUiFilters) => void;
  showMedia: boolean;
}) {
  const [cameras, setCameras] = useState<MotionCameraOption[]>([]);

  useEffect(() => {
    let alive = true;
    getMotionCameras()
      .then((c) => {
        if (alive) setCameras(c);
      })
      .catch(() => {
        // 카메라 옵션 실패는 필터만 비활성 — 큐 로딩과 분리(조용히 무시).
      });
    return () => {
      alive = false;
    };
  }, []);

  const selected = new Set(value.camera_id ?? []);
  function toggleCamera(id: string) {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    onChange({ ...value, camera_id: next.size ? Array.from(next) : undefined });
  }

  return (
    <div className="space-y-3">
      <DateControls
        value={{ date_from: value.date_from, date_to: value.date_to }}
        onChange={(range) =>
          onChange({ ...value, date_from: range.date_from, date_to: range.date_to })
        }
      />

      {cameras.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          <span className="self-center text-xs text-zinc-400">카메라</span>
          {cameras.map((cam) => (
            <button
              key={cam.id}
              type="button"
              onClick={() => toggleCamera(cam.id)}
              className={chipClass(selected.has(cam.id))}
            >
              {cam.name}
            </button>
          ))}
        </div>
      )}

      {showMedia && (
        <div className="flex flex-wrap gap-1.5">
          <span className="self-center text-xs text-zinc-400">재생</span>
          {MEDIA_OPTIONS.map((opt) => (
            <button
              key={opt.value || 'all'}
              type="button"
              onClick={() =>
                onChange({ ...value, media: opt.value === '' ? undefined : opt.value })
              }
              className={chipClass((value.media ?? '') === opt.value)}
            >
              {opt.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
