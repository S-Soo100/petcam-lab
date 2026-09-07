// 움직임 구간 내비게이션(순수) — GME 상태 구간 중 'moving' 만 모아 타임라인 마커·점프 대상으로 쓴다.
//
// 왜 병합하나: GME 는 track 별로 구간을 따로 내서 같은 시각에 여러 'moving' 이 겹치거나 0.1초 끊김이 잦다.
// 사람이 볼 땐 "한 번의 움직임"이라 0.5초 이내 끊김은 이어 붙인다. 점프는 구간 시작 0.5초 전으로 가서
// 움직임의 시작을 놓치지 않게 한다(라벨링 v4 스펙 §5 UX ①, 2026-09-08).
import type { GmeStateInterval } from './gmeOverlay';

export interface MovingSpan {
  start_sec: number;
  end_sec: number;
}

export const MOVING_JOIN_GAP_SEC = 0.5;
export const MOVING_JUMP_LEAD_SEC = 0.5;
// 이 시간 안에서 이미 시작한 구간은 "다음"이 아니라 "지금" 구간으로 본다.
const NEXT_EPSILON_SEC = 0.25;

export function mergeMovingSpans(intervals: readonly GmeStateInterval[], joinGapSec = MOVING_JOIN_GAP_SEC): MovingSpan[] {
  const moving = intervals
    .filter((i) => i.state === 'moving' && Number.isFinite(i.start_sec) && Number.isFinite(i.end_sec) && i.end_sec > i.start_sec)
    .map((i) => ({ start_sec: i.start_sec, end_sec: i.end_sec }))
    .sort((a, b) => a.start_sec - b.start_sec);
  const out: MovingSpan[] = [];
  for (const span of moving) {
    const last = out[out.length - 1];
    if (last && span.start_sec <= last.end_sec + joinGapSec) last.end_sec = Math.max(last.end_sec, span.end_sec);
    else out.push({ ...span });
  }
  return out;
}

export function movingTotalSec(spans: readonly MovingSpan[]): number {
  return spans.reduce((sum, s) => sum + (s.end_sec - s.start_sec), 0);
}

// 점프 목적지 — 구간 시작 0.5초 전(0 미만이면 0).
export function jumpTargetSec(span: MovingSpan): number {
  return Math.max(0, span.start_sec - MOVING_JUMP_LEAD_SEC);
}

// 현재 시각이 속한 구간 index(리드 포함). 없으면 -1.
export function currentSpanIndex(spans: readonly MovingSpan[], currentSec: number): number {
  return spans.findIndex((s) => currentSec >= jumpTargetSec(s) && currentSec <= s.end_sec);
}

// "다음 움직임" 대상 index — 현재 시각 뒤에 시작하는 첫 구간, 없으면 처음으로 되감기(구간이 있을 때). 구간 없으면 null.
export function nextSpanIndex(spans: readonly MovingSpan[], currentSec: number): number | null {
  if (spans.length === 0) return null;
  const idx = spans.findIndex((s) => s.start_sec > currentSec + NEXT_EPSILON_SEC);
  return idx === -1 ? 0 : idx;
}

export const PLAYBACK_SPEEDS = [1, 1.5, 2] as const;
export type PlaybackSpeed = (typeof PLAYBACK_SPEEDS)[number];

export function isPlaybackSpeed(v: unknown): v is PlaybackSpeed {
  return (PLAYBACK_SPEEDS as readonly number[]).includes(v as number);
}
