import Button from '@/components/ui/Button';
import { Card, CardTitle } from '@/components/ui/Card';
import type { BoundaryDecision, BoundaryPairSummary } from '@/lib/rbaBoundaryServer';
import ReviewVideo from '../_review-video';

const OPTIONS: { value: BoundaryDecision; label: string; help: string }[] = [
  { value: 'same_event', label: '같은 사건', help: '한 행동이 다음 영상까지 이어져 보여' },
  { value: 'different_event', label: '다른 사건', help: '행동이 끝났거나 새 행동으로 보여' },
  { value: 'uncertain', label: '잘 모르겠음', help: '영상만으로 이어짐을 판단하기 어려워' },
];

export default function BoundaryPairView({ pair, urls, selected, submitting, onSelect, onSubmit }: {
  pair: BoundaryPairSummary;
  urls: { left: string; right: string } | null;
  selected: BoundaryDecision | null;
  submitting: boolean;
  onSelect: (decision: BoundaryDecision) => void;
  onSubmit: () => void;
}) {
  return (
    <div className="space-y-4">
      <Card>
        <CardTitle>문제 {pair.ordinal}</CardTitle>
        <p className="mt-1 text-sm text-zinc-600">영상 A를 먼저 보고 B까지 이어서 봐줘. 행동 이름은 붙이지 않아.</p>
        <p className="mt-1 text-xs text-zinc-500">두 영상 사이 미촬영 시간 약 {pair.gap_sec.toFixed(1)}초</p>
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
        <CardTitle>두 영상은 같은 사건이야?</CardTitle>
        <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-3">
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
          {submitting ? '저장 중…' : '이 판정으로 제출'}
        </Button>
        <p className="mt-2 text-center text-xs text-zinc-500">제출하면 답을 바꿀 수 없어.</p>
      </Card>
    </div>
  );
}
