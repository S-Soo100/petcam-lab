'use client';

// 튜토리얼 피드백 — 서버 comparison 을 세 그룹으로 렌더(설계 §4.5). 숫자 총점·'불합격' 문구는
// 표시하지 않는다. 모든 값은 공통 표시 계층으로 한국어화하며 raw enum·JSON 을 절대 노출하지 않는다.
// '왜'/'다음 영상에서' 문구는 feedback_content 에서 병합한다.

import Badge from '@/components/ui/Badge';
import { Card, CardTitle } from '@/components/ui/Card';
import { dimensionLabel, formatDimensionValue } from '@/lib/labelingDisplay';
import type { FeedbackContent, TutorialComparison } from '@/lib/labelingTutorial';

export function TutorialFeedback({
  comparison,
  feedback,
}: {
  comparison: TutorialComparison;
  feedback: FeedbackContent;
}) {
  const matched = comparison.dimensions.filter((d) => d.group === 'matched');
  const review = comparison.dimensions.filter((d) => d.group === 'review');
  const subjective = comparison.dimensions.filter((d) => d.group === 'subjective');

  return (
    <div className="space-y-4">
      {review.length > 0 && (
        <Card className="space-y-3 border-amber-200 bg-amber-50">
          <CardTitle>기준과 다른 항목</CardTitle>
          {review.map((d) => {
            const fb = feedback[d.key];
            return (
              <div key={d.key} className="rounded-lg bg-white p-3 ring-1 ring-amber-100">
                <div className="text-sm font-medium text-zinc-800">{dimensionLabel(d.key)}</div>
                <div className="mt-1 grid gap-1 text-xs">
                  <div><span className="text-zinc-500">라벨러 판정</span> · {formatDimensionValue(d.key, d.yours)}</div>
                  <div><span className="text-zinc-500">기준 답</span> · {formatDimensionValue(d.key, d.reference)}</div>
                  {fb?.why && <div className="mt-1 text-amber-900">왜: {fb.why}</div>}
                  {fb?.next && <div className="text-amber-900">다음 영상에서: {fb.next}</div>}
                </div>
              </div>
            );
          })}
        </Card>
      )}

      {matched.length > 0 && (
        <Card className="border-emerald-200 bg-emerald-50">
          <CardTitle>기준과 같음</CardTitle>
          <div className="mt-2 flex flex-wrap gap-2">
            {matched.map((d) => (
              <Badge key={d.key} tone="success">{dimensionLabel(d.key)}</Badge>
            ))}
          </div>
        </Card>
      )}

      {subjective.length > 0 && (
        <Card padding="sm">
          <details>
            <summary className="cursor-pointer text-xs font-medium text-zinc-600">
              사람마다 다르게 판단할 수 있는 항목 ({subjective.length})
            </summary>
            <p className="mt-2 text-xs text-zinc-500">
              이 항목은 하나의 정답으로 고정하지 않아. 사람마다 다르게 판단할 수 있으며 틀린 답으로 처리하지 않아.
            </p>
            <div className="mt-2 space-y-1 text-xs text-zinc-600">
              {subjective.map((d) => (
                <div key={d.key}>
                  <span className="text-zinc-500">{dimensionLabel(d.key)}</span> · 라벨러 판정 {formatDimensionValue(d.key, d.yours)} · 기준 답 {formatDimensionValue(d.key, d.reference)}
                </div>
              ))}
            </div>
          </details>
        </Card>
      )}
    </div>
  );
}
