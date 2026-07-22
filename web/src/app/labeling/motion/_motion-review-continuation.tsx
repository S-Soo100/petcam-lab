'use client';

// 분류 결과 확인 + 결정 취소 + 다음 미분류 영상 Card(설계 §7.2).
//
// 분류 성공 직후 강제 탭 이동 대신 이 Card 로 결과를 확인시키고, owner 가 스스로 "결정 취소"나
// "다음 미분류 영상"을 고르게 한다(자동 다음 이동 없음). label 이면 지금 GT 작성 CTA 도 함께 보인다.
// 표시 규칙은 React 렌더 없이 검증할 수 있게 순수 view-model(_motion-review-continuation-view)로 분리한다.

import type { MotionLabelingState } from '@/lib/labelingV3';
import Button from '@/components/ui/Button';
import { Card, CardTitle } from '@/components/ui/Card';
import { motionContinuationView } from './_motion-review-continuation-view';

export default function MotionReviewContinuation({
  state,
  nextBusy = false,
  nextFailed = false,
  undoBusy = false,
  onUndo,
  onNext,
  onWriteGtNow,
}: {
  state: MotionLabelingState;
  nextBusy?: boolean;
  nextFailed?: boolean;
  undoBusy?: boolean;
  onUndo: () => void;
  onNext: () => void;
  onWriteGtNow: () => void;
}) {
  const view = motionContinuationView({ state, nextBusy, nextFailed });
  const anyBusy = nextBusy || undoBusy;

  return (
    <Card className="space-y-3 border-emerald-200 bg-emerald-50">
      <CardTitle>{view.statusText}</CardTitle>
      <div className="flex flex-wrap gap-2">
        {view.showGtCta && (
          <Button variant="primary" size="sm" disabled={anyBusy} onClick={onWriteGtNow}>
            지금 사람 판정 작성
          </Button>
        )}
        <Button variant="primary" size="sm" disabled={view.nextDisabled || undoBusy} onClick={onNext}>
          {nextBusy ? '이동 중…' : view.nextLabel}
        </Button>
        <Button variant="secondary" size="sm" disabled={anyBusy} onClick={onUndo}>
          {undoBusy ? '되돌리는 중…' : '결정 취소'}
        </Button>
      </div>
      {view.showNextRetry && (
        <p className="text-xs text-amber-700">
          다음 영상을 찾지 못했어. 저장은 그대로야 —
          <button type="button" className="ml-1 underline" disabled={anyBusy} onClick={onNext}>
            다음 영상 다시 찾기
          </button>
        </p>
      )}
    </Card>
  );
}
