'use client';

// owner 불일치 최종 판정(설계 §4.5). 두 최초 제출을 side-by-side 로 보고 A 채택 / B 채택 / 새 판정.
// 원본 resolution 은 서버가 append-only 이력으로 보존한다(overwrite 금지). owner 전용.

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';

import { Card, CardTitle } from '@/components/ui/Card';
import Button from '@/components/ui/Button';
import { SelectionCard } from '@/components/ui/SelectionControl';
import { ApiError } from '@/lib/labelingApi';
import {
  applyVisibilityChange,
  collectGroundTruthIssues,
  type GroundTruthField,
  type GroundTruthInput,
  type GroundTruthValidationIssue,
  type ObservedAction,
  type Visibility,
} from '@/lib/labelingV2';
import { ACTION_LABELS, VISIBILITY_LABELS, describeSegment } from '@/lib/labelingDisplay';
import { BLIND_DECISION_COPY, type BlindDecision, type BlindReasonCode } from '@/lib/motionBlindReview';
import {
  getBlindClipFileUrl,
  getOwnerConflictDetail,
  resolveOwnerConflict,
  type OwnerConflictDetail,
  type OwnerSubmissionView,
} from '@/lib/motionBlindReviewApi';
import {
  GroundTruthForm,
  VideoPlayer,
  emptyGt,
  freshSegment,
} from '../../../_labeling-forms';
import {
  OWNER_DIFFERING_TITLE,
  OWNER_RESOLVE_LABELS,
  ownerDifferingFieldLabels,
} from '../../../_blind-review-view';

const REASON_LABELS: Record<string, string> = {
  behavior_data: '행동 있음',
  ambiguous: '애매함',
  gecko_absent: '게코 없음',
  capture_error: '촬영 오류',
  media_error: '재생 오류',
};

function SubmissionColumn({ label, sub, changed }: { label: string; sub: OwnerSubmissionView | null; changed: Set<string> }) {
  if (!sub) return <Card className="text-sm text-zinc-500">{label}: 제출 없음</Card>;
  const gt = sub.initial_gt as GroundTruthInput | null;
  return (
    <Card className="space-y-1">
      <div className="text-xs font-semibold text-zinc-500">{label}</div>
      <div className={`text-sm font-medium ${changed.has('decision') ? 'text-amber-800' : 'text-zinc-900'}`}>
        {BLIND_DECISION_COPY[sub.decision as BlindDecision]?.title ?? sub.decision}
        <span className="ml-1 text-xs text-zinc-500">({REASON_LABELS[sub.reason_code] ?? sub.reason_code})</span>
      </div>
      {gt && (
        <>
          <p className={`text-sm ${changed.has('primary_action') ? 'text-amber-800' : 'text-zinc-800'}`}>
            {ACTION_LABELS[gt.primary_action] ?? gt.primary_action} · {VISIBILITY_LABELS[gt.visibility] ?? gt.visibility}
          </p>
          {gt.segments.length > 0 && (
            <p className={`text-xs ${changed.has('segments') ? 'text-amber-800' : 'text-zinc-600'}`}>
              {gt.segments.map((s) => describeSegment(s)).join(' · ')}
            </p>
          )}
        </>
      )}
      {sub.note && <p className="text-xs text-zinc-500">메모: {sub.note}</p>}
    </Card>
  );
}

export default function OwnerConflictDetailPage() {
  const router = useRouter();
  const { clipId } = useParams<{ clipId: string }>();

  const [detail, setDetail] = useState<OwnerConflictDetail | null>(null);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [reason, setReason] = useState('');

  // 새 판정 상태
  const [newMode, setNewMode] = useState(false);
  const [newDecision, setNewDecision] = useState<BlindDecision | null>(null);
  const [newReason, setNewReason] = useState<BlindReasonCode>('gecko_absent');
  const [gt, setGt] = useState<GroundTruthInput>(() => emptyGt(60));
  const [selected, setSelected] = useState<Set<GroundTruthField>>(() => new Set());
  const [issues, setIssues] = useState<GroundTruthValidationIssue[]>([]);
  const duration = detail?.clip ? Number(detail.clip.duration_sec) || 60 : 60;

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const d = await getOwnerConflictDetail(clipId);
        if (!alive) return;
        setDetail(d);
        if (d.clip?.media_ready) {
          try {
            const { url } = await getBlindClipFileUrl(clipId);
            if (alive) setVideoUrl(url);
          } catch {
            /* video 없어도 판정 가능 */
          }
        }
      } catch (e) {
        if (alive) setError(e instanceof ApiError ? e.message : (e as Error).message);
      } finally {
        if (alive) setBusy(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [clipId]);

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
      ? gt.observed_actions.filter((i) => i !== action)
      : [...gt.observed_actions, action];
    patchGt('observed_actions', nextObserved);
    patchGt(
      'segments',
      enabled ? gt.segments.filter((s) => s.action !== action) : [...gt.segments, freshSegment(action, duration)],
    );
    if (!nextObserved.some((i) => i.endsWith('_interaction'))) {
      patchGt('enrichment_object', 'none');
      patchGt('interaction_types', []);
    }
  }
  function updateSegment(action: ObservedAction, key: 'start_sec' | 'end_sec', value: number) {
    patchGt('segments', gt.segments.map((s) => (s.action === action ? { ...s, [key]: value } : s)));
  }

  async function resolve(choice: 'a' | 'b' | 'new') {
    if (!detail) return;
    let finalDecision: BlindDecision | undefined;
    let finalGt: GroundTruthInput | null = null;
    if (choice === 'new') {
      if (!newDecision) {
        setError('새 판정을 먼저 골라줘.');
        return;
      }
      finalDecision = newDecision;
      if (newDecision === 'label') {
        const local = collectGroundTruthIssues(gt, duration, selected);
        if (local.length > 0) {
          setIssues(local);
          return;
        }
        setIssues([]);
        finalGt = gt;
      }
    }
    setSaving(true);
    setError(null);
    try {
      await resolveOwnerConflict({
        clipId,
        choice,
        finalDecision,
        finalGt,
        reason: reason || null,
        expectedUpdatedAt: detail.updated_at,
      });
      router.push('/labeling/blind/conflicts');
    } catch (e) {
      setError(e instanceof ApiError ? e.message : (e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  if (busy) return <main className="mx-auto max-w-3xl px-4 py-6 text-sm text-zinc-500">불러오는 중…</main>;
  if (!detail)
    return (
      <main className="mx-auto max-w-3xl space-y-3 px-4 py-6">
        <Card className="border-rose-200 bg-rose-50 text-sm text-rose-800">{error ?? '대상을 찾을 수 없어.'}</Card>
        <Link className="text-sm text-emerald-700 underline" href="/labeling/blind/conflicts">목록으로</Link>
      </main>
    );

  const changed = new Set(detail.differing_fields);
  const reasonForNew = (): BlindReasonCode =>
    newDecision === 'label' ? 'behavior_data' : newDecision === 'hold' ? 'ambiguous' : newReason;
  void reasonForNew;

  return (
    <main className="mx-auto max-w-3xl space-y-3 px-4 py-6">
      <CardTitle>불일치 검수</CardTitle>
      <VideoPlayer src={videoUrl} />

      {detail.differing_fields.length > 0 && (
        <Card className="border-amber-200 bg-amber-50 text-sm text-amber-900">
          <div className="font-semibold">{OWNER_DIFFERING_TITLE}</div>
          <div className="mt-1 text-xs">{ownerDifferingFieldLabels(detail.differing_fields).join(', ')}</div>
        </Card>
      )}

      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        <SubmissionColumn label="라벨러 A" sub={detail.submission_a} changed={changed} />
        <SubmissionColumn label="라벨러 B" sub={detail.submission_b} changed={changed} />
      </div>

      <label className="block text-sm font-medium">
        판정 사유 (선택)
        <textarea
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          maxLength={2000}
          className="mt-1 min-h-16 w-full rounded-lg border border-zinc-300 p-2 text-sm"
        />
      </label>

      {error && <Card className="border-rose-200 bg-rose-50 text-sm text-rose-800">{error}</Card>}

      <div className="flex flex-wrap gap-2">
        <Button variant="labelingPrimary" size="md" disabled={saving} onClick={() => resolve('a')}>
          {OWNER_RESOLVE_LABELS.a}
        </Button>
        <Button variant="labelingPrimary" size="md" disabled={saving} onClick={() => resolve('b')}>
          {OWNER_RESOLVE_LABELS.b}
        </Button>
        <Button variant="labelingSecondary" size="md" onClick={() => setNewMode((v) => !v)}>
          새 판정 만들기
        </Button>
      </div>

      {newMode && (
        <Card className="space-y-2">
          <div className="grid grid-cols-1 gap-2">
            {(['label', 'hold', 'exclude'] as BlindDecision[]).map((dec) => (
              <SelectionCard
                key={dec}
                pressed={newDecision === dec}
                tone={dec === 'label' ? 'success' : dec === 'hold' ? 'warning' : 'danger'}
                title={BLIND_DECISION_COPY[dec].title}
                description={BLIND_DECISION_COPY[dec].description}
                onClick={() => setNewDecision(dec)}
              />
            ))}
          </div>
          {newDecision === 'exclude' && (
            <div className="flex flex-wrap gap-2">
              {(['gecko_absent', 'capture_error', 'media_error'] as BlindReasonCode[]).map((r) => (
                <SelectionCard
                  key={r}
                  pressed={newReason === r}
                  tone="danger"
                  title={REASON_LABELS[r]}
                  description=""
                  className="w-auto"
                  onClick={() => setNewReason(r)}
                />
              ))}
            </div>
          )}
          {newDecision === 'label' && (
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
              onSave={() => resolve('new')}
              saveLabel={OWNER_RESOLVE_LABELS.new}
            />
          )}
          {newDecision && newDecision !== 'label' && (
            <Button variant="labelingPrimary" size="md" disabled={saving} onClick={() => resolve('new')}>
              {OWNER_RESOLVE_LABELS.new}
            </Button>
          )}
        </Card>
      )}
    </main>
  );
}
