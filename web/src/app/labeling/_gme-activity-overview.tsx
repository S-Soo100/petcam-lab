'use client';

import { Card, CardTitle } from '@/components/ui/Card';
import type { GmeMotionState, GmeStateInterval } from '@/lib/gmeOverlay';

export interface GmeActivitySummary {
  moving_sec: number;
  visible_sec: number;
  static_sec: number;
  unknown_sec: number;
  camera_motion_sec: number;
  not_visible_sec: number;
}

const STATE_COPY: Record<GmeMotionState, { label: string; className: string }> = {
  moving: { label: '움직임', className: 'bg-emerald-500' },
  static: { label: '정지', className: 'bg-slate-400' },
  unknown: { label: '미확정', className: 'bg-amber-400' },
  camera_motion: { label: '카메라 움직임', className: 'bg-violet-500' },
  not_visible: { label: '미관측', className: 'bg-zinc-200' },
};

function roundTenth(value: number): number {
  return Math.round((value + Number.EPSILON) * 10) / 10;
}

function seconds(value: number): string {
  return `${roundTenth(value)}초`;
}

function secondRange(start: number, end: number): string {
  return `${roundTenth(start)}–${roundTenth(end)}초`;
}

function fillUnknownGaps(
  intervals: GmeStateInterval[],
  durationSec: number,
): GmeStateInterval[] {
  const completed: GmeStateInterval[] = [];
  let cursor = 0;
  for (const interval of intervals) {
    if (interval.start_sec > cursor) {
      completed.push({
        start_sec: cursor,
        end_sec: interval.start_sec,
        state: 'unknown',
        track_indexes: [],
      });
    }
    completed.push(interval);
    cursor = interval.end_sec;
  }
  if (cursor < durationSec) {
    completed.push({
      start_sec: cursor,
      end_sec: durationSec,
      state: 'unknown',
      track_indexes: [],
    });
  }
  return completed;
}

export function summarizeGmeIntervals(
  intervals: GmeStateInterval[],
  durationSec: number,
): GmeActivitySummary {
  const sums: Record<GmeMotionState, number> = {
    moving: 0,
    static: 0,
    unknown: 0,
    camera_motion: 0,
    not_visible: 0,
  };
  for (const interval of intervals) {
    sums[interval.state] += interval.end_sec - interval.start_sec;
  }
  const covered = Object.values(sums).reduce((total, value) => total + value, 0);
  // 구간이 빠진 시간은 "게코가 안 보임"이 아니라 분석 결과가 불완전한 상태야.
  sums.unknown += Math.max(0, durationSec - covered);
  const moving = roundTenth(sums.moving);
  const staticSec = roundTenth(sums.static);
  return {
    moving_sec: moving,
    visible_sec: roundTenth(moving + staticSec),
    static_sec: staticSec,
    unknown_sec: roundTenth(sums.unknown),
    camera_motion_sec: roundTenth(sums.camera_motion),
    not_visible_sec: roundTenth(sums.not_visible),
  };
}

export function GmeActivityOverview({
  durationSec,
  intervals,
  currentTimeSec,
}: {
  durationSec: number;
  intervals: GmeStateInterval[];
  currentTimeSec: number;
}) {
  const summary = summarizeGmeIntervals(intervals, durationSec);
  const timelineIntervals = fillUnknownGaps(intervals, durationSec);
  const position = durationSec > 0
    ? Math.min(100, Math.max(0, (currentTimeSec / durationSec) * 100))
    : 0;
  const metrics = [
    ['게코가 움직인 시간', summary.moving_sec],
    ['게코가 보인 시간', summary.visible_sec],
    ['게코가 정지한 시간', summary.static_sec],
    ['판정 불확실', summary.unknown_sec],
  ] as const;

  return (
    <Card className="space-y-4 border-sky-200 bg-sky-50">
      <div className="space-y-1">
        <CardTitle>GME 전체 활동 요약</CardTitle>
        <p className="text-xs text-sky-800">
          영상 재생과 관계없이 미리 계산된 결과야. 박스가 보이는 시간과 실제 움직인 시간은 달라.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
        {metrics.map(([label, value]) => (
          <div key={label} className="rounded-md bg-white px-3 py-2 ring-1 ring-inset ring-sky-100">
            <p className="text-xs text-zinc-600">{label}</p>
            <p className="text-lg font-semibold tabular-nums text-zinc-900">{seconds(value)}</p>
          </div>
        ))}
      </div>

      <div className="space-y-2">
        <p className="text-xs font-semibold text-zinc-700">전체 상태 타임라인</p>
        <div className="relative h-5 overflow-hidden rounded bg-zinc-200" aria-label="전체 상태 타임라인">
          {durationSec > 0 && timelineIntervals.map((interval, index) => {
            const copy = STATE_COPY[interval.state];
            return (
              <span
                key={`${interval.start_sec}-${interval.end_sec}-${index}`}
                className={`absolute inset-y-0 ${copy.className}`}
                style={{
                  left: `${(interval.start_sec / durationSec) * 100}%`,
                  width: `${((interval.end_sec - interval.start_sec) / durationSec) * 100}%`,
                }}
                title={`${copy.label} ${secondRange(interval.start_sec, interval.end_sec)}`}
              />
            );
          })}
          <span
            className="absolute inset-y-0 w-0.5 bg-zinc-950"
            style={{ left: `${position}%` }}
            title={`현재 위치 ${seconds(currentTimeSec)}`}
          />
        </div>
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-zinc-600">
          {Object.entries(STATE_COPY).map(([state, copy]) => (
            <span key={state} className="inline-flex items-center gap-1.5">
              <span className={`h-2.5 w-2.5 rounded-sm ${copy.className}`} />
              {copy.label}
            </span>
          ))}
        </div>
      </div>
    </Card>
  );
}
