'use client';

// 튜토리얼 피드백 — 서버 comparison 을 일치/다시 보기/개인차 가능 3그룹으로 렌더(설계 §10).
// 숫자 총점·'불합격' 문구는 표시하지 않는다. '왜'/'다음 영상에서' 문구는 feedback_content.

import Badge from '@/components/ui/Badge';
import { Card, CardTitle } from '@/components/ui/Card';
import type { FeedbackContent, TutorialComparison } from '@/lib/labelingTutorial';

const DIM_LABELS: Record<string, string> = {
  visibility: '가시성',
  primary_action: '대표 행동',
  target: '행동 대상',
  activity_intensity: '활동 강도',
  enrichment_object: 'enrichment object',
  observed_actions: '관찰 행동',
  interaction_types: '상호작용 유형',
  segments: '행동 구간',
  vlm_verdict: 'VLM 판정',
  vlm_error_tags: 'VLM 오류 유형',
  human_confidence: '사람 확신도',
  context_tags: '환경 태그',
  note: '메모',
};

function fmt(value: unknown): string {
  if (value === null || value === undefined || value === '') return '없음';
  if (Array.isArray(value)) return value.length ? value.map((v) => fmt(v)).join(', ') : '없음';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

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
          <CardTitle>다시 볼 기준</CardTitle>
          {review.map((d) => {
            const fb = feedback[d.key];
            return (
              <div key={d.key} className="rounded-lg bg-white p-3 ring-1 ring-amber-100">
                <div className="text-sm font-medium text-zinc-800">{DIM_LABELS[d.key] ?? d.key}</div>
                <div className="mt-1 grid gap-1 text-xs">
                  <div><span className="text-zinc-500">네 답</span> · {fmt(d.yours)}</div>
                  <div><span className="text-zinc-500">기준</span> · {fmt(d.reference)}</div>
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
          <CardTitle>일치</CardTitle>
          <div className="mt-2 flex flex-wrap gap-2">
            {matched.map((d) => (
              <Badge key={d.key} tone="success">{DIM_LABELS[d.key] ?? d.key}</Badge>
            ))}
          </div>
        </Card>
      )}

      {subjective.length > 0 && (
        <Card padding="sm">
          <details>
            <summary className="cursor-pointer text-xs font-medium text-zinc-600">
              개인차 가능 ({subjective.length})
            </summary>
            <div className="mt-2 space-y-1 text-xs text-zinc-600">
              {subjective.map((d) => (
                <div key={d.key}>
                  <span className="text-zinc-500">{DIM_LABELS[d.key] ?? d.key}</span> · 네 답 {fmt(d.yours)} · 기준 {fmt(d.reference)}
                </div>
              ))}
            </div>
          </details>
        </Card>
      )}
    </div>
  );
}
