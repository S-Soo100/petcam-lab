'use client';

// owner 전용 현재 GT 보정 패널(설계 §7.4). completed 세션에서 owner 에게만 노출된다.
// 최초 blind GT(initial_gt)는 건드리지 않고 current_gt 와 VLM review 만 사유와 함께 보정한다.
// 저장 전에 바뀐 필드 요약을 한 번 확인시키고, 성공하면 보정 시각·사유를 표시한다.
// 일반 labeler 에게는 이 컴포넌트가 렌더링되지 않는다(page 의 owner 게이트).

import { useEffect, useState } from 'react';

import Button from '@/components/ui/Button';
import { Card, CardTitle } from '@/components/ui/Card';
import { useToast } from '@/components/Toast';
import { ApiError, reviseGroundTruth } from '@/lib/labelingApi';
import {
  applyVisibilityChange,
  changedGroundTruthFields,
  collectGroundTruthIssues,
  firstIssueField,
  validateVlmReview,
  type GroundTruthField,
  type GroundTruthInput,
  type GroundTruthValidationIssue,
  type LabelingSession,
  type ObservedAction,
  type Visibility,
  type VlmReviewInput,
} from '@/lib/labelingV2';
import { GroundTruthForm, VlmReviewCard, allSelectedFields, fieldAnchorId, freshSegment } from './_labeling-forms';

const FIELD_LABELS: Record<keyof GroundTruthInput, string> = {
  visibility: '가시성', primary_action: '대표 행동', observed_actions: '세부 행동',
  segments: '행동 구간', target: '대표 행동 대상', human_confidence: '사람 확신도',
  context_tags: '환경 태그', activity_intensity: '활동 강도', highlight_recommendation: '하이라이트 여부',
  enrichment_object: '놀이 대상', interaction_types: '상호작용 유형', note: '메모',
};

function clone(gt: GroundTruthInput): GroundTruthInput {
  return JSON.parse(JSON.stringify(gt)) as GroundTruthInput;
}

export function CorrectionPanel({ clipId, session, duration, onRevised, onCancel }: {
  clipId: string;
  session: LabelingSession;
  duration: number;
  onRevised: (result: { session: LabelingSession; revised_at: string | null }) => void;
  onCancel: () => void;
}) {
  const toast = useToast();
  const baseGt = session.current_gt as GroundTruthInput;
  const [gt, setGt] = useState<GroundTruthInput>(() => clone(baseGt));
  // 보정은 이미 확정된 답을 여는 것이므로 모든 필드가 직접 선택된 것으로 본다.
  const [selected, setSelected] = useState<Set<GroundTruthField>>(() => allSelectedFields());
  const [issues, setIssues] = useState<GroundTruthValidationIssue[]>([]);
  const [review, setReview] = useState<VlmReviewInput>({
    verdict: session.vlm_verdict ?? 'correct',
    error_tags: session.vlm_error_tags ?? [],
    note: session.vlm_review_note ?? null,
  });
  const [reason, setReason] = useState('');
  // 확인 단계에서 고정한 payload 스냅샷. null 이면 아직 확인 전.
  const [confirmed, setConfirmed] = useState<null | {
    gt: GroundTruthInput; review: VlmReviewInput; reason: string;
  }>(null);
  const [saving, setSaving] = useState(false);
  const confirming = confirmed !== null;

  const prediction = session.prediction_snapshot ?? null;
  const gtChanges = changedGroundTruthFields(baseGt, gt);
  const verdictChanged = review.verdict !== session.vlm_verdict;
  const errorTagsChanged =
    JSON.stringify(review.error_tags) !== JSON.stringify(session.vlm_error_tags ?? []);
  const reviewNoteChanged = (review.note ?? null) !== (session.vlm_review_note ?? null);

  // 확인 단계 진입 후 GT·VLM review·사유 중 하나라도 바뀌면 확인을 무효화한다.
  // 저장은 confirmed 스냅샷만 쓰므로, 확인 요약과 실제 저장 payload 가 어긋날 수 없다.
  useEffect(() => {
    setConfirmed((current) => (current === null ? current : null));
  }, [gt, review, reason]);

  function patchGt<K extends keyof GroundTruthInput>(key: K, value: GroundTruthInput[K]) {
    setGt((current) => ({ ...current, [key]: value }));
    if (key !== 'note') setSelected((current) => new Set(current).add(key as GroundTruthField));
  }
  function selectVisibility(visibility: Visibility) {
    const next = applyVisibilityChange(gt, selected, visibility);
    setGt(next.gt);
    setSelected(next.selected);
  }
  function toggleObserved(action: ObservedAction) {
    const enabled = gt.observed_actions.includes(action);
    const nextObserved = enabled
      ? gt.observed_actions.filter((item) => item !== action)
      : [...gt.observed_actions, action];
    patchGt('observed_actions', nextObserved);
    patchGt('segments', enabled
      ? gt.segments.filter((segment) => segment.action !== action)
      : [...gt.segments, freshSegment(action, duration)]);
    if (!nextObserved.some((item) => item.endsWith('_interaction'))) {
      patchGt('enrichment_object', 'none');
      patchGt('interaction_types', []);
    }
  }
  function updateSegment(action: ObservedAction, key: 'start_sec' | 'end_sec', value: number) {
    patchGt('segments', gt.segments.map((segment) =>
      segment.action === action ? { ...segment, [key]: value } : segment));
  }

  function scrollToFirstIssue(list: GroundTruthValidationIssue[]) {
    const field = firstIssueField(list);
    if (!field) return;
    document.getElementById(fieldAnchorId(field))?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  // 1단계: 검증 + 바뀐 필드 요약 확인. 통과하면 확인 payload 를 스냅샷으로 고정한다.
  function review_() {
    const localIssues = collectGroundTruthIssues(gt, duration, selected);
    if (localIssues.length > 0) {
      setIssues(localIssues); scrollToFirstIssue(localIssues);
      toast.show('보정 전에 표시된 항목을 채워줘', 'error');
      return;
    }
    setIssues([]);
    // VLM 검수도 확인 단계에서 client 검증(서버 validateVlmReview 와 같은 규칙).
    try {
      validateVlmReview(review);
    } catch (error) {
      toast.show(`VLM 검수: ${(error as Error).message}`, 'error');
      return;
    }
    if (reason.trim().length < 10) {
      toast.show('보정 사유를 10자 이상 적어줘', 'error');
      return;
    }
    if (gtChanges.length === 0 && !verdictChanged && !errorTagsChanged && !reviewNoteChanged) {
      toast.show('바뀐 내용이 없어', 'error');
      return;
    }
    setConfirmed({
      gt: clone(gt),
      review: {
        verdict: review.verdict,
        error_tags: [...review.error_tags],
        note: review.note ?? null,
      },
      reason: reason.trim(),
    });
  }

  // 2단계: 확인한 스냅샷만 저장한다. 확인 후 편집분은 useEffect 가 이미 확인을 풀어줘서 여기 못 온다.
  async function save() {
    if (!confirmed) return;
    setSaving(true);
    try {
      const result = await reviseGroundTruth(clipId, {
        gt: confirmed.gt,
        vlm_review: confirmed.review,
        reason: confirmed.reason,
      });
      toast.show('현재 GT를 보정했어', 'success');
      onRevised(result);
    } catch (cause) {
      if (cause instanceof ApiError && cause.issues && cause.issues.length > 0) {
        setIssues(cause.issues); setConfirmed(null); scrollToFirstIssue(cause.issues);
      }
      const message = cause instanceof ApiError ? cause.message : (cause as Error).message;
      toast.show(`보정 실패: ${message}`, 'error');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-4">
      <Card className="border-amber-300 bg-amber-50">
        <CardTitle>현재 GT 보정 (owner 전용)</CardTitle>
        <p className="mt-2 text-sm text-amber-900">
          최초 blind GT는 보존돼. 아래 수정은 <strong>현재 기준 답과 감사 기록만</strong> 갱신해.
        </p>
        <p className="mt-1 text-xs text-amber-800">보정 사유는 감사 기록에 남고 화면에 표시될 수 있어. 비밀값은 넣지 마.</p>
      </Card>

      <GroundTruthForm
        gt={gt}
        duration={duration}
        saving={saving}
        explicitlySelected={selected}
        issues={issues}
        patchGt={patchGt}
        onSelectVisibility={selectVisibility}
        toggleObserved={toggleObserved}
        updateSegment={updateSegment}
        onSave={review_}
        saveLabel="보정 검토"
      />

      {prediction && (
        <VlmReviewCard
          prediction={prediction}
          humanGt={gt}
          review={review}
          setReview={setReview}
          saving={saving}
          completed
          onComplete={() => undefined}
          owner
        />
      )}

      <Card className="space-y-3">
        <label className="block text-sm font-medium">보정 사유 (10~500자, 필수)
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            maxLength={500}
            placeholder="예: 기준 GT 대상 오기입 정정 — wheel 은 놀이 근거로, target 은 물그릇으로."
            className="mt-2 min-h-20 w-full rounded-lg border border-zinc-300 p-3 font-normal outline-none focus:border-zinc-900"
          />
          <span className="mt-1 block text-xs text-zinc-400">{reason.trim().length}/500</span>
        </label>

        {confirming ? (
          <div className="rounded-lg bg-zinc-100 p-4 text-sm">
            <p className="font-medium">이대로 보정할까?</p>
            <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-zinc-700">
              {gtChanges.map((key) => <li key={key}>{FIELD_LABELS[key]} 변경</li>)}
              {verdictChanged && <li>VLM 판정 변경</li>}
              {errorTagsChanged && <li>VLM 오류 유형 변경</li>}
              {reviewNoteChanged && <li>VLM 검수 메모 변경</li>}
            </ul>
            <div className="mt-3 flex gap-2">
              <Button size="sm" disabled={saving} onClick={save}>{saving ? '저장 중…' : '보정 저장'}</Button>
              <Button size="sm" variant="secondary" disabled={saving} onClick={() => setConfirmed(null)}>다시 수정</Button>
            </div>
          </div>
        ) : (
          <div className="flex gap-2">
            <Button size="sm" variant="secondary" onClick={onCancel}>취소</Button>
          </div>
        )}
      </Card>
    </div>
  );
}
