import Button from '@/components/ui/Button';
import { Card, CardTitle } from '@/components/ui/Card';
import type {
  BoundaryEligibilityDecision,
  BoundaryPairSummary,
} from '@/lib/rbaBoundaryServer';
import ReviewVideo from '../_review-video';

type EligibilityOption = {
  value: BoundaryEligibilityDecision;
  label: string;
};

type EligibilityGroup = {
  title: string;
  help: string;
  className: string;
  selectedClassName: string;
  options: EligibilityOption[];
};

const INVALID_GROUPS: EligibilityGroup[] = [
  {
    title: '게코가 안 보임',
    help: '영상은 정상인데 게코 자체를 확인할 수 없는 경우',
    className: 'border-amber-200 bg-amber-50/60',
    selectedClassName: 'border-amber-600 bg-amber-100',
    options: [
      { value: 'left_gecko_absent', label: 'A에 게코 없음' },
      { value: 'right_gecko_absent', label: 'B에 게코 없음' },
      { value: 'both_gecko_absent', label: '둘 다 게코 없음' },
    ],
  },
  {
    title: '실제 게코 활동 없음',
    help: '게코는 보이지만 그림자·빛·곤충 등이 움직여 잘못 감지된 경우',
    className: 'border-orange-200 bg-orange-50/60',
    selectedClassName: 'border-orange-600 bg-orange-100',
    options: [
      { value: 'left_no_gecko_activity', label: 'A에 실제 활동 없음' },
      { value: 'right_no_gecko_activity', label: 'B에 실제 활동 없음' },
      { value: 'both_no_gecko_activity', label: '둘 다 실제 활동 없음' },
    ],
  },
  {
    title: '영상 자체를 확인할 수 없음',
    help: '재생 실패·검은 화면·멈춤·심한 가림이나 노출 오류가 있는 경우',
    className: 'border-rose-200 bg-rose-50/60',
    selectedClassName: 'border-rose-600 bg-rose-100',
    options: [
      { value: 'left_capture_or_media_error', label: 'A 영상 확인 불가' },
      { value: 'right_capture_or_media_error', label: 'B 영상 확인 불가' },
      { value: 'both_capture_or_media_error', label: '둘 다 영상 확인 불가' },
    ],
  },
];

function DecisionButton({ option, selected, selectedClassName, onSelect }: {
  option: EligibilityOption;
  selected: BoundaryEligibilityDecision | null;
  selectedClassName: string;
  onSelect: (decision: BoundaryEligibilityDecision) => void;
}) {
  return (
    <button
      type="button"
      data-decision={option.value}
      onClick={() => onSelect(option.value)}
      aria-pressed={selected === option.value}
      className={`min-h-12 rounded-lg border-2 px-3 py-2 text-left text-sm font-semibold text-zinc-900 ${
        selected === option.value ? selectedClassName : 'border-zinc-200 bg-white'
      }`}
    >
      {option.label}
    </button>
  );
}

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
        <p className="mt-1 text-sm text-zinc-600">A와 B에서 게코가 보이는지, 실제로 움직이는지, 영상이 정상인지 확인해줘. 아직 이어짐은 판단하지 않아.</p>
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
        <div className="mt-3 rounded-xl border border-emerald-200 bg-emerald-50/60 p-3">
          <p className="text-sm font-bold text-emerald-950">유효</p>
          <p className="mt-0.5 text-xs text-emerald-800">두 영상 모두에서 게코의 실제 활동을 확인할 수 있는 경우</p>
          <button
            type="button"
            data-decision="eligible"
            onClick={() => onSelect('eligible')}
            aria-pressed={selected === 'eligible'}
            className={`mt-2 min-h-14 w-full rounded-lg border-2 px-3 py-2 text-left ${
              selected === 'eligible' ? 'border-emerald-700 bg-emerald-100' : 'border-emerald-300 bg-white'
            }`}
          >
            <span className="block text-sm font-bold text-emerald-950">두 영상 모두 유효</span>
            <span className="mt-0.5 block text-xs text-emerald-800">A와 B 모두 실제 게코 활동이 보여</span>
          </button>
        </div>
        <div className="mt-3 space-y-3">
          {INVALID_GROUPS.map((group) => (
            <section key={group.title} className={`rounded-xl border p-3 ${group.className}`}>
              <h3 className="text-sm font-bold text-zinc-950">{group.title}</h3>
              <p className="mt-0.5 text-xs text-zinc-600">{group.help}</p>
              <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-3">
                {group.options.map((option) => (
                  <DecisionButton
                    key={option.value}
                    option={option}
                    selected={selected}
                    selectedClassName={group.selectedClassName}
                    onSelect={onSelect}
                  />
                ))}
              </div>
            </section>
          ))}
        </div>
        <Button variant="labelingPrimary" className="mt-4 w-full" disabled={!selected || submitting} onClick={onSubmit}>
          {submitting ? '저장 중…' : '이 자격 판정으로 제출'}
        </Button>
        <p className="mt-2 text-center text-xs text-zinc-500">제출한 원본은 바뀌지 않아. 잘못 제출했다면 별도 정정 기록이 필요해.</p>
      </Card>
    </div>
  );
}
