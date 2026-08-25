'use client';

import Button from '@/components/ui/Button';
import { selectGmeOverlayPoints, type GmeOverlayPoint } from '@/lib/gmeOverlay';

export function GmeVideoOverlay({
  points,
  currentTimeSec,
}: {
  points: GmeOverlayPoint[];
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
        return (
          <rect
            key={point.track_index}
            x={x}
            y={y}
            width={width}
            height={height}
            fill="none"
            stroke={observed ? '#22c55e' : '#38bdf8'}
            strokeWidth={3}
            strokeDasharray={observed ? undefined : '8 6'}
            vectorEffect="non-scaling-stroke"
          />
        );
      })}
    </svg>
  );
}

export function GmeMissReportPanel({
  available,
  currentTimeSec,
  saving,
  status,
  onReport,
}: {
  available: boolean;
  currentTimeSec: number;
  saving: boolean;
  status: string | null;
  onReport: () => void;
}) {
  return (
    <section className="space-y-2 rounded-lg border border-sky-200 bg-sky-50 p-3 text-sm text-sky-950">
      <p className="font-semibold">GME 박스는 참고용이야</p>
      <p className="text-xs text-sky-800">
        박스가 없어도 게코가 있을 수 있어. 영상 전체를 직접 보고 사람 판정을 먼저 해줘.
      </p>
      {!available && <p className="text-xs text-zinc-600">이 영상은 표시할 GME 박스가 없어.</p>}
      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="secondary"
          size="md"
          disabled={!available || saving}
          onClick={onReport}
        >
          {saving ? '기록 중…' : 'YOLO가 게코를 놓쳤어'}
        </Button>
        <span className="text-xs tabular-nums text-sky-800">현재 {currentTimeSec.toFixed(2)}초</span>
      </div>
      {status && <p role="status" className="text-xs font-medium text-sky-900">{status}</p>}
    </section>
  );
}
