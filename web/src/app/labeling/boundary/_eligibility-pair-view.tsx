import Button from '@/components/ui/Button';
import { Card, CardTitle } from '@/components/ui/Card';
import type {
  BoundaryEligibilityDecision,
  BoundaryPairSummary,
} from '@/lib/rbaBoundaryServer';
import ReviewVideo from '../_review-video';

const OPTIONS: {
  value: BoundaryEligibilityDecision;
  label: string;
  help: string;
}[] = [
  { value: 'eligible', label: '둘 다 게코가 보여 — 유효', help: '두 영상 모두에서 게코를 확인할 수 있어' },
  { value: 'left_gecko_absent', label: '영상 A에 게코가 없어', help: 'A에서는 게코를 확인할 수 없어' },
  { value: 'right_gecko_absent', label: '영상 B에 게코가 없어', help: 'B에서는 게코를 확인할 수 없어' },
  { value: 'both_gecko_absent', label: '둘 다 게코가 없어', help: 'A와 B 모두 게코를 확인할 수 없어' },
  { value: 'capture_or_media_error', label: '촬영 오류 또는 화면 확인 불가', help: '파일 오류·검은 화면·심한 흔들림 등으로 볼 수 없어' },
];

export default function EligibilityPairView({ pair, urls, selected, submitting, onSelect, onSubmit }: {
  pair: BoundaryPairSummary;
  urls: { left: string; right: string } | null;
  selected: BoundaryEligibilityDecision | null;
  submitting: boolean;
  onSelect: (decision: BoundaryEligibilityDecision) => void;
  onSubmit: () => void;
}) {
  return (
    <div className="space-y-4">
      <Card>
        <CardTitle>1단계 · 영상 자격 확인 {pair.ordinal}</CardTitle>
        <p className="mt-1 text-sm text-zinc-600">A와 B에서 게코가 실제로 보이는지만 확인해줘. 아직 이어짐은 판단하지 않아.</p>
      </Card>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {(['left', 'right'] as const).map((side, index) => (
          <Card key={side} padding="sm">
            <p className="mb-2 text-sm font-semibold">{index + 1}/2 · 영상 {index === 0 ? 'A' : 'B'}</p>
            {urls ? (
              <ReviewVideo src={urls[side]} />
            ) : <div className="grid aspect-video place-items-center rounded-lg bg-zinc-100 text-sm text-zinc-500">영상 준비 중…</div>}
          </Card>
        ))}
      </div>
      <Card>
        <CardTitle>이 두 영상은 이어짐 문제로 쓸 수 있어?</CardTitle>
        <p className="mt-1 text-xs text-amber-700">행동이 작거나 이어지는지 판단이 어렵다는 이유만으로 무효로 고르지는 마.</p>
        <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
          {OPTIONS.map((option) => (
            <button key={option.value} type="button" onClick={() => onSelect(option.value)}
              aria-pressed={selected === option.value}
              className={`min-h-20 rounded-lg border-2 p-3 text-left ${selected === option.value ? 'border-emerald-600 bg-emerald-50' : 'border-zinc-200 bg-white'}`}>
              <span className="block text-sm font-semibold text-zinc-900">{option.label}</span>
              <span className="mt-1 block text-xs text-zinc-500">{option.help}</span>
            </button>
          ))}
        </div>
        <Button variant="labelingPrimary" className="mt-4 w-full" disabled={!selected || submitting} onClick={onSubmit}>
          {submitting ? '저장 중…' : '이 자격 판정으로 제출'}
        </Button>
        <p className="mt-2 text-center text-xs text-zinc-500">제출하면 답을 바꿀 수 없어.</p>
      </Card>
    </div>
  );
}
