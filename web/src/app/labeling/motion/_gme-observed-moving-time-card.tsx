import { Card, CardTitle } from '@/components/ui/Card';
import { formatGmeObservedMovingTime } from '@/lib/gmeObservedMovingTime';
import type { GmeObservedMovingTime } from '@/lib/labelingV3';


export default function GmeObservedMovingTimeCard({
  metric,
}: {
  metric: GmeObservedMovingTime;
}) {
  const copy = formatGmeObservedMovingTime(metric);
  return (
    <Card className="space-y-2 border-emerald-200 bg-emerald-50">
      <CardTitle>GME 관측 움직임 시간</CardTitle>
      <p className="text-base font-semibold text-emerald-900">{copy.title}</p>
      <p className="text-sm text-emerald-800">{copy.detail}</p>
      <p className="text-xs text-emerald-700">
        영상에서 게코가 보인 구간만 계산한 참고값이며, 행동 정답이나 건강 진단이 아니야.
      </p>
    </Card>
  );
}
