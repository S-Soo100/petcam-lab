'use client';

// owner 팀 큐 분류 컨트롤 — 라벨 대상 | 보류 | 제외 | 초기화(설계 §5.3).
//
// skip 만 확인창(진행 중 세션이 있으면 서버가 409 로 막고, 되돌리기 비용이 큰 결정이라).
// label/hold/reset 은 되돌릴 수 있어 확인 없이 즉시. expected_updated_at 으로 optimistic
// concurrency — 다른 탭에서 상태가 바뀌었으면 409 stale_state 로 새로고침을 유도한다.

import { useState } from 'react';

import { ApiError } from '@/lib/labelingApi';
import type { MotionDecisionChange, MotionLabelingState } from '@/lib/labelingV3';
import { decideMotionClip, type MotionDecision } from '@/lib/labelingV3Api';
import Button from '@/components/ui/Button';

const STATE_LABEL: Record<MotionLabelingState, string> = {
  unreviewed: '미분류',
  label: '라벨 대상',
  hold: '보류',
  skip: '제외',
};

export default function MotionDecisionControls({
  clipId,
  state,
  stateUpdatedAt,
  onDecided,
}: {
  clipId: string;
  state: MotionLabelingState;
  stateUpdatedAt: string | null;
  // 성공 전 state 를 previous 로 캡처해 넘긴다 — 상세가 결과 안내·결정 취소(undo)에 쓴다(설계 §7.1).
  onDecided: (change: MotionDecisionChange) => void;
}) {
  const [busy, setBusy] = useState<MotionDecision | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function decide(decision: MotionDecision) {
    if (decision === 'skip' && !window.confirm('이 영상을 라벨링 대상에서 제외할까? 라벨링이 이미 시작됐으면 제외할 수 없어.')) {
      return;
    }
    setBusy(decision);
    setError(null);
    try {
      const result = await decideMotionClip(clipId, {
        decision,
        expected_updated_at: stateUpdatedAt,
      });
      onDecided({ previous: state, next: result.state, updatedAt: result.updated_at });
    } catch (e) {
      if (e instanceof ApiError && e.code === 'stale_state') {
        setError('다른 화면에서 상태가 바뀌었어. 새로고침 후 다시 시도해.');
      } else if (e instanceof ApiError && e.code === 'labeling_started') {
        setError('이미 라벨링이 시작되어 제외할 수 없어.');
      } else {
        setError(e instanceof ApiError ? e.message : (e as Error).message);
      }
    } finally {
      setBusy(null);
    }
  }

  // 판정 CTA 는 의미별 라벨링 전용 variant(설계 §4.6): label→초록, 제외→빨강, 보류→중립.
  const decisions: {
    key: MotionDecision;
    label: string;
    variant: 'labelingPrimary' | 'labelingSecondary' | 'labelingDanger';
  }[] = [
    { key: 'label', label: '라벨 대상으로 보내기', variant: 'labelingPrimary' },
    { key: 'hold', label: '보류', variant: 'labelingSecondary' },
    { key: 'skip', label: '제외', variant: 'labelingDanger' },
  ];

  return (
    <div className="space-y-2 rounded-lg border border-zinc-200 bg-white p-4">
      <div className="text-xs text-zinc-500">
        현재 분류: <span className="font-medium text-zinc-800">{STATE_LABEL[state]}</span>
      </div>
      <div className="flex flex-wrap gap-2">
        {decisions.map((d) => (
          <Button
            key={d.key}
            variant={d.variant}
            size="sm"
            disabled={busy !== null || state === d.key}
            onClick={() => decide(d.key)}
          >
            {busy === d.key ? '처리 중…' : d.label}
          </Button>
        ))}
        {state !== 'unreviewed' && (
          <Button
            variant="labelingSecondary"
            size="sm"
            disabled={busy !== null}
            onClick={() => decide('reset')}
          >
            {busy === 'reset' ? '처리 중…' : '분류 초기화'}
          </Button>
        )}
      </div>
      {error && <p className="text-xs text-red-600">{error}</p>}
    </div>
  );
}
