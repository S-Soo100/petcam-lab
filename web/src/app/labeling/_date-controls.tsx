'use client';

// 라벨링 큐 KST 날짜 컨트롤(§4.6).
//
//   [오늘] [어제] [최근 3일] [최근 7일]
//   [← 이전 날] [2026-07-08] [다음 날 →] [전체 기간]
//   현재 범위: 2026년 7월 8일 하루
//
// - 이전·다음 날은 단일 날짜 범위일 때만 활성화.
// - 범위는 항상 `+09:00` 오프셋 ISO 로 URL 에 남겨 새로고침·공유가 된다.
// - 모바일에서는 두 줄 wrap 을 허용하고 가로 스크롤을 만들지 않는다(flex-wrap).

import { useEffect, useState } from 'react';

import {
  type DatePreset,
  type DateRange,
  describeRange,
  presetRange,
  singleDayOf,
  singleDayRange,
  stepDay,
} from '@/lib/labelingDateRange';
import Button from '@/components/ui/Button';
import { SelectionChip } from '@/components/ui/SelectionControl';

const PRESETS: { key: DatePreset; label: string }[] = [
  { key: 'today', label: '오늘' },
  { key: 'yesterday', label: '어제' },
  { key: 'last3', label: '최근 3일' },
  { key: 'last7', label: '최근 7일' },
];

export default function DateControls({
  value,
  onChange,
}: {
  value: DateRange;
  onChange: (next: DateRange) => void;
}) {
  // 프리셋 활성 표시는 '오늘' 기준이 필요하다. SSR/hydration 불일치를 피하려고
  // now 는 마운트 후에만 잡는다(초기 렌더는 강조 없음).
  const [now, setNow] = useState<Date | null>(null);
  useEffect(() => {
    setNow(new Date());
  }, []);

  const single = singleDayOf(value);
  const isAllTime = !value.date_from && !value.date_to;

  const activePreset =
    now &&
    PRESETS.find((p) => {
      const r = presetRange(p.key, now);
      return r.date_from === value.date_from && r.date_to === value.date_to;
    })?.key;

  return (
    <div className="space-y-2 rounded-md bg-zinc-50 px-3 py-2 ring-1 ring-inset ring-zinc-200">
      <div className="flex flex-wrap items-center gap-2">
        {PRESETS.map((p) => (
          <SelectionChip
            key={p.key}
            pressed={activePreset === p.key}
            tone="neutral"
            onClick={() => onChange(presetRange(p.key, new Date()))}
          >
            {p.label}
          </SelectionChip>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          variant="secondary"
          disabled={!single}
          onClick={() => {
            const next = stepDay(value, -1);
            if (next) onChange(next);
          }}
        >
          ← 이전 날
        </Button>
        <input
          type="date"
          value={single ?? ''}
          onChange={(e) =>
            onChange(e.target.value ? singleDayRange(e.target.value) : {})
          }
          className="rounded-md border border-zinc-300 bg-white px-2 py-1 text-sm text-zinc-700"
        />
        <Button
          size="sm"
          variant="secondary"
          disabled={!single}
          onClick={() => {
            const next = stepDay(value, 1);
            if (next) onChange(next);
          }}
        >
          다음 날 →
        </Button>
        <Button
          size="sm"
          variant={isAllTime ? 'primary' : 'secondary'}
          onClick={() => onChange({})}
        >
          전체 기간
        </Button>
      </div>

      <p className="text-xs text-zinc-500">
        현재 범위: <span className="font-medium text-zinc-700">{describeRange(value)}</span>
      </p>
    </div>
  );
}
