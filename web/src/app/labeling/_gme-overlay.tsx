'use client';

import Button from '@/components/ui/Button';
import {
  selectGmeOverlayPoints,
  selectGmeStateAtTime,
  type GmeFeedbackKind,
  type GmeMotionState,
  type GmeOverlayPoint,
  type GmeStateInterval,
} from '@/lib/gmeOverlay';

const STATE_STROKE: Record<GmeMotionState, string> = {
  moving: '#22c55e',
  static: '#94a3b8',
  unknown: '#f59e0b',
  camera_motion: '#8b5cf6',
  not_visible: '#d4d4d8',
};

export function GmeVideoOverlay({
  points,
  intervals,
  currentTimeSec,
}: {
  points: GmeOverlayPoint[];
  intervals?: GmeStateInterval[];
  currentTimeSec: number;
}) {
  const visible = selectGmeOverlayPoints(points, currentTimeSec);
  return (
    <svg
      aria-hidden="true"
      className="pointer-events-none absolute inset-0 h-full w-full"
      viewBox="0 0 1 1"
      preserveAspectRatio="none"
    >
      {visible.map((point) => {
        const [x, y, width, height] = point.bbox_norm;
        const observed = point.provenance === 'observed';
        const state = intervals
          ? selectGmeStateAtTime(intervals, currentTimeSec, point.track_index)
          : null;
        return (
          <rect
            key={point.track_index}
            x={x}
            y={y}
            width={width}
            height={height}
            fill="none"
            stroke={state ? STATE_STROKE[state] : (observed ? '#22c55e' : '#38bdf8')}
            strokeWidth={3}
            strokeDasharray={observed ? undefined : '8 6'}
            vectorEffect="non-scaling-stroke"
          />
        );
      })}
    </svg>
  );
}

export function GmeFeedbackReportPanel({
  available,
  stateAware = false,
  points,
  currentTimeSec,
  saving,
  status,
  onReport,
  onConfirmAbsent,
}: {
  available: boolean;
  stateAware?: boolean;
  points: GmeOverlayPoint[];
  currentTimeSec: number;
  saving: boolean;
  status: string | null;
  onReport: (feedbackKind: GmeFeedbackKind) => void;
  onConfirmAbsent?: () => void;
}) {
  const wholeVideoNoBox = available && points.length === 0;
  const currentHasBox = available
    && selectGmeOverlayPoints(points, currentTimeSec).length > 0;

  return (
    <section className="space-y-2 rounded-lg border border-sky-200 bg-sky-50 p-3 text-sm text-sky-950">
      <p className="font-semibold">GME 박스는 참고용이야</p>
      <p className="text-xs text-sky-800">
        {stateAware
          ? '박스는 게코 탐지 위치야. 회색은 정지, 초록은 움직임, 노랑은 미확정이야. 박스가 없어도 게코가 있을 수 있어.'
          : '박스가 없어도 게코가 있을 수 있어. 박스가 틀릴 수도 있으니 영상 전체를 직접 보고 사람 판정을 먼저 해줘.'}
      </p>
      {!available && <p className="text-xs text-zinc-600">GME 결과를 확인할 수 없어. 사람 판정은 계속할 수 있어.</p>}
      {wholeVideoNoBox && (
        <p className="rounded-md bg-amber-100 px-2 py-1 text-xs font-semibold text-amber-900">
          영상 전체에서 GME 탐지 없음
        </p>
      )}
      {available && points.length > 0 && !currentHasBox && (
        <p className="text-xs text-zinc-600">현재 시각에는 GME 박스가 없어.</p>
      )}
      <div className="flex flex-wrap items-center gap-2">
        {wholeVideoNoBox && onConfirmAbsent && (
          <Button variant="primary" size="md" disabled={saving} onClick={onConfirmAbsent}>
            {saving ? '저장 중…' : '게코 없음 확인'}
          </Button>
        )}
        <Button variant="secondary" size="md" disabled={!available || saving}
          onClick={() => onReport('miss')}>
          {saving ? '기록 중…' : 'YOLO가 게코를 놓쳤어'}
        </Button>
        <Button variant="secondary" size="md" disabled={!currentHasBox || saving}
          onClick={() => onReport('false_positive')}>
          {saving ? '기록 중…' : '게코가 없는데 박스가 있어'}
        </Button>
        <Button variant="secondary" size="md" disabled={!currentHasBox || saving}
          onClick={() => onReport('bad_box')}>
          {saving ? '기록 중…' : '게코는 있는데 박스가 틀렸어'}
        </Button>
        <span className="text-xs tabular-nums text-sky-800">현재 {currentTimeSec.toFixed(2)}초</span>
      </div>
      {status && <p role="status" className="text-xs font-medium text-sky-900">{status}</p>}
    </section>
  );
}
