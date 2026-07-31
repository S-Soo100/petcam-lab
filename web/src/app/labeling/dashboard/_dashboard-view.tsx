import { ACTION_LABELS } from '@/lib/labelingDisplay';
import type { PrimaryAction } from '@/lib/labelingV2';
import type { LabelingDataDashboard } from '@/lib/rbaBoundaryServer';
import { Card, CardTitle } from '@/components/ui/Card';

function number(value: number) {
  return new Intl.NumberFormat('ko-KR').format(value);
}

export default function DashboardView({ data }: { data: LabelingDataDashboard }) {
  const rows = Object.entries(data.behavior_counts).sort((a, b) => b[1] - a[1]);
  const max = Math.max(1, ...rows.map(([, count]) => count));
  return (
    <div className="space-y-5 py-6">
      <div>
        <h1 className="text-xl font-bold text-zinc-950">데이터 현황</h1>
        <p className="mt-1 text-sm text-zinc-600">팀 전체가 함께 보는 영상과 사람 정답 누적 현황이야.</p>
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {[
          ['영상 기록', data.video_record_count, 'DB에 기록된 전체 영상'],
          ['재생 가능', data.playable_video_count, 'DB 기준 원본이 연결된 영상'],
          ['GT 완료', data.gt_labeled_video_count, '최종 행동 정답이 있는 영상'],
        ].map(([label, value, help]) => (
          <Card key={String(label)}>
            <p className="text-xs font-medium text-zinc-500">{label}</p>
            <p className="mt-2 text-3xl font-bold tabular-nums text-zinc-950">{number(value as number)}</p>
            <p className="mt-1 text-xs text-zinc-500">{help}</p>
          </Card>
        ))}
      </div>
      <Card>
        <CardTitle>행동별 GT</CardTitle>
        <p className="mt-1 text-xs text-zinc-500">GT 완료 영상의 대표 행동 분포야.</p>
        <div className="mt-4 space-y-3">
          {rows.length === 0 && <p className="text-sm text-zinc-500">아직 완료된 행동 정답이 없어.</p>}
          {rows.map(([action, count]) => (
            <div key={action}>
              <div className="mb-1 flex items-center justify-between gap-3 text-sm">
                <span className="font-medium text-zinc-800">
                  {ACTION_LABELS[action as PrimaryAction] ?? '기타 행동'}
                </span>
                <span className="tabular-nums text-zinc-600">{number(count)}</span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-zinc-100">
                <div className="h-full rounded-full bg-emerald-600" style={{ width: `${(count / max) * 100}%` }} />
              </div>
            </div>
          ))}
        </div>
      </Card>
      <p className="text-xs text-zinc-500">
        집계 시각 {new Date(data.generated_at).toLocaleString('ko-KR')} · 재생 가능 수는 DB 기준이야.
      </p>
    </div>
  );
}
