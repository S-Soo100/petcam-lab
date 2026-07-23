'use client';

import { useState } from 'react';

import type { InteractionType } from '@/lib/labelingV2';
import {
  interactionSelectionSummary,
  shouldOpenSecondaryWheelChoices,
  wheelInteractionGroups,
  wheelInteractionQuestion,
  WHEEL_SEGMENT_END_HELP,
} from '@/lib/labelingDisplay';
import { SelectionCard } from '@/components/ui/SelectionControl';
import Button from '@/components/ui/Button';

// 쳇바퀴 상호작용 단계형 입력(설계 §4.7). 접촉 방식/결과를 같은 위계로 나열하지 않고 관찰 순서
// (ride → rotate → push)로 먼저 묻고, chase/repeated_return/other 는 '다른 행동도 기록하기'
// 아래 보조 영역에 둔다. 저장 enum·payload 는 변경하지 않는다 — onToggle 은 기존 enum 값 그대로 넘긴다.
export function WheelInteractionFields({
  selected,
  onToggle,
}: {
  selected: InteractionType[];
  onToggle: (type: InteractionType) => void;
}) {
  const groups = wheelInteractionGroups();
  const [disclosureOpen, setDisclosureOpen] = useState(false);
  // 비동기로 복원된 draft(이미 보조 enum 선택)도 열리도록 disclosure 상태와 OR 한다.
  const secondaryVisible = disclosureOpen || shouldOpenSecondaryWheelChoices(selected);
  const summary = interactionSelectionSummary('wheel', selected);

  const renderCard = (type: InteractionType) => {
    const question = wheelInteractionQuestion(type);
    const active = selected.includes(type);
    return (
      <SelectionCard
        key={type}
        pressed={active}
        tone="neutral"
        title={question.title}
        description={active ? question.selectedLabel : '예/아니오로 선택해'}
        onClick={() => onToggle(type)}
      />
    );
  };

  return (
    <div>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">{groups.primary.map(renderCard)}</div>
      {!secondaryVisible && (
        <Button
          variant="labelingSecondary"
          size="md"
          className="mt-3 w-full"
          aria-expanded={false}
          onClick={() => setDisclosureOpen(true)}
        >
          다른 행동도 기록하기
        </Button>
      )}
      {secondaryVisible && (
        <div className="mt-3">
          <p className="text-xs font-medium text-violet-900">그 밖에 함께 본 행동</p>
          <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
            {groups.secondary.map(renderCard)}
          </div>
        </div>
      )}
      {summary && (
        <p className="mt-3 rounded-lg bg-violet-100 px-3 py-2 text-xs font-medium text-violet-900">
          {summary}
        </p>
      )}
    </div>
  );
}

// 쳇바퀴 구간 종료시간 아래에 항상 표시하는 종료 시점·계속 상호작용 기준(설계 §4.7).
// '떠남' enum 을 추가하지 않는다 — 그냥 떠나면 구간만 종료, 밖에서 계속 밀면 상호작용 지속.
export function WheelSegmentEndHelp() {
  return (
    <div className="mt-2 rounded-lg bg-violet-50 px-3 py-2 text-xs leading-5 text-violet-800">
      {WHEEL_SEGMENT_END_HELP.map((line) => (
        <p key={line}>{line}</p>
      ))}
    </div>
  );
}
