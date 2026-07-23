'use client';

// 라벨러 이중 블라인드 영상 판정 workspace(설계 §4.2·§8). live 상세와 canary 상세가 공유한다 —
// scope(cohortId)는 prop 으로 고정한다(canary 는 path, live 는 query). 상대 판정·VLM 은 절대 부르지
// 않고, lease 토큰은 브라우저 생성 + per-tab sessionStorage 에만 두고 성공 뒤 지운다(설계 §5.1·§8).

import { useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';

import Button from '@/components/ui/Button';
import { Card, CardTitle } from '@/components/ui/Card';
import { SelectionCard } from '@/components/ui/SelectionControl';
import { ApiError } from '@/lib/labelingApi';
import {
  applyVisibilityChange,
  collectGroundTruthIssues,
  firstIssueField,
  type GroundTruthField,
  type GroundTruthInput,
  type GroundTruthValidationIssue,
  type ObservedAction,
  type Visibility,
} from '@/lib/labelingV2';
import {
  BLIND_COMPARATOR_VERSION,
  BLIND_DECISION_COPY,
  type BlindDecision,
  type BlindReasonCode,
} from '@/lib/motionBlindReview';
import {
  claimBlindReview,
  getBlindClip,
  getBlindClipFileUrl,
  getBlindQueue,
  submitBlindReview,
  type BlindSubmitResult,
} from '@/lib/motionBlindReviewApi';
import type { BlindClipDetail } from '@/lib/motionBlindReviewServer';
import { useLabelingUserId } from './_owner-context';
import { GroundTruthForm, VideoPlayer, emptyGt, fieldAnchorId, freshSegment } from './_labeling-forms';
import { BLIND_EXCLUDE_REASONS, blindSubmitResultMessage } from './_blind-review-view';

const DECISION_TONES: Record<BlindDecision, 'success' | 'warning' | 'danger'> = {
  label: 'success',
  hold: 'warning',
  exclude: 'danger',
};

function newLeaseToken(): string {
  return crypto.randomUUID();
}

export function BlindReviewDetail({
  clipId,
  cohortId,
  activityDay,
}: {
  clipId: string;
  cohortId: string | null;
  activityDay: string | null;
}) {
  const router = useRouter();
  const userId = useLabelingUserId();

  const scopeKey = cohortId ?? 'live';
  const leaseStorageKey = `petcam-blind-lease:${clipId}:${scopeKey}`;
  const draftKey = `petcam-blind-draft:${userId ?? 'anon'}:${clipId}:${activityDay ?? 'na'}:${BLIND_COMPARATOR_VERSION}`;

  const [detail, setDetail] = useState<BlindClipDetail | null>(null);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [decision, setDecision] = useState<BlindDecision | null>(null);
  const [reason, setReason] = useState<BlindReasonCode>('gecko_absent');
  const [gt, setGt] = useState<GroundTruthInput>(() => emptyGt(60));
  const [selected, setSelected] = useState<Set<GroundTruthField>>(() => new Set());
  const [issues, setIssues] = useState<GroundTruthValidationIssue[]>([]);
  const [duration, setDuration] = useState(60);

  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState<BlindSubmitResult | null>(null);
  const [leaseHeld, setLeaseHeld] = useState(true);
  const [staleLease, setStaleLease] = useState(false);
  const leaseTokenRef = useRef<string | null>(null);

  const acquireLease = useCallback(async () => {
    let token: string;
    try {
      token = sessionStorage.getItem(leaseStorageKey) ?? newLeaseToken();
      sessionStorage.setItem(leaseStorageKey, token);
    } catch {
      token = newLeaseToken();
    }
    leaseTokenRef.current = token;
    try {
      await claimBlindReview({ clipId, leaseToken: token, cohortId });
      setLeaseHeld(true);
      setStaleLease(false);
    } catch (e) {
      if (e instanceof ApiError && e.code === 'slot_in_use') setLeaseHeld(false);
      else if (e instanceof ApiError && e.code === 'stale_lease') setStaleLease(true);
    }
  }, [clipId, cohortId, leaseStorageKey]);

  useEffect(() => {
    let alive = true;
    (async () => {
      setBusy(true);
      setError(null);
      try {
        const d = await getBlindClip(clipId, cohortId);
        if (!alive) return;
        setDetail(d);
        const dur = Number(d.duration_sec) || 60;
        setDuration(dur);
        setGt(emptyGt(dur));
        if (d.media_ready) {
          try {
            const { url } = await getBlindClipFileUrl(clipId, cohortId);
            if (alive) setVideoUrl(url);
          } catch {
            /* 재생 URL 실패는 판정을 막지 않는다(제외 경로 제공). */
          }
        }
        if (!d.own_submitted) await acquireLease();
      } catch (e) {
        if (alive) setError(e instanceof ApiError ? e.message : (e as Error).message);
      } finally {
        if (alive) setBusy(false);
      }
    })();
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clipId, cohortId]);

  useEffect(() => {
    if (result || detail?.own_submitted) return;
    const id = setInterval(() => {
      if (document.visibilityState === 'visible' && leaseHeld) void acquireLease();
    }, 10 * 60 * 1000);
    return () => clearInterval(id);
  }, [result, detail?.own_submitted, leaseHeld, acquireLease]);

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
    patchGt(
      'segments',
      enabled
        ? gt.segments.filter((segment) => segment.action !== action)
        : [...gt.segments, freshSegment(action, duration)],
    );
    if (!nextObserved.some((item) => item.endsWith('_interaction'))) {
      patchGt('enrichment_object', 'none');
      patchGt('interaction_types', []);
    }
  }
  function updateSegment(action: ObservedAction, key: 'start_sec' | 'end_sec', value: number) {
    patchGt(
      'segments',
      gt.segments.map((segment) => (segment.action === action ? { ...segment, [key]: value } : segment)),
    );
  }

  const reasonForDecision = (dec: BlindDecision): BlindReasonCode =>
    dec === 'label' ? 'behavior_data' : dec === 'hold' ? 'ambiguous' : reason;

  async function submit() {
    if (!decision) return;
    let initialGt: GroundTruthInput | null = null;
    if (decision === 'label') {
      const local = collectGroundTruthIssues(gt, duration, selected);
      if (local.length > 0) {
        setIssues(local);
        const field = firstIssueField(local);
        if (field) document.getElementById(fieldAnchorId(field))?.scrollIntoView({ behavior: 'smooth', block: 'center' });
        return;
      }
      setIssues([]);
      initialGt = gt;
    }
    setSaving(true);
    setError(null);
    const token = leaseTokenRef.current;
    if (!token) {
      setError('작업 권한을 다시 받아야 해.');
      setSaving(false);
      return;
    }
    try {
      const res = await submitBlindReview({
        clipId,
        decision,
        initialGt,
        note: gt.note,
        reasonCode: reasonForDecision(decision),
        leaseToken: token,
        cohortId,
      });
      setResult(res);
      try {
        sessionStorage.removeItem(leaseStorageKey);
        localStorage.removeItem(draftKey);
      } catch {
        /* ignore */
      }
    } catch (e) {
      if (e instanceof ApiError && e.code === 'stale_lease') {
        setStaleLease(true);
        await acquireLease();
      } else if (e instanceof ApiError && e.code === 'already_submitted') {
        setError('이미 제출한 영상이야.');
      } else {
        setError(e instanceof ApiError ? e.message : (e as Error).message);
      }
    } finally {
      setSaving(false);
    }
  }

  async function goNext() {
    if (cohortId) {
      router.push(`/labeling/blind/canary/${cohortId}`);
      return;
    }
    if (!activityDay) {
      router.push('/labeling');
      return;
    }
    try {
      const res = await getBlindQueue({ activityDay, limit: 1 });
      const next = res.items[0];
      router.push(next ? `/labeling/blind/${next.id}?activity_day=${activityDay}` : '/labeling');
    } catch {
      router.push('/labeling');
    }
  }

  if (busy) return <main className="mx-auto max-w-3xl px-4 py-6 text-sm text-zinc-500">불러오는 중…</main>;
  if (error && !detail)
    return (
      <main className="mx-auto max-w-3xl space-y-3 px-4 py-6">
        <Card className="border-rose-200 bg-rose-50 text-sm text-rose-800">{error}</Card>
        <Link className="text-sm text-emerald-700 underline" href={cohortId ? `/labeling/blind/canary/${cohortId}` : '/labeling'}>돌아가기</Link>
      </main>
    );

  const alreadyDone = result != null || detail?.own_submitted;

  return (
    <main className="mx-auto max-w-3xl space-y-3 px-4 py-6">
      {cohortId && (
        <div className="inline-flex w-fit rounded-full bg-sky-100 px-2.5 py-0.5 text-xs font-semibold text-sky-900">
          검증용 작업
        </div>
      )}
      <VideoPlayer src={videoUrl} />

      {alreadyDone ? (
        <Card className="space-y-3 border-emerald-200 bg-emerald-50">
          <CardTitle>{result ? blindSubmitResultMessage(result) : '저장 완료 · 상대 판정 대기 중'}</CardTitle>
          <div className="flex gap-2">
            <Button variant="labelingPrimary" size="md" onClick={goNext}>다음 영상</Button>
            <Link className="self-center text-sm text-zinc-500 underline" href={cohortId ? `/labeling/blind/canary/${cohortId}` : '/labeling'}>목록으로</Link>
          </div>
        </Card>
      ) : (
        <>
          {!leaseHeld && (
            <Card className="border-amber-200 bg-amber-50 text-sm text-amber-900">
              다른 창에서 이 영상을 작업 중이야. 이 창에서는 제출할 수 없어.
            </Card>
          )}
          {staleLease && (
            <Card className="border-amber-200 bg-amber-50 text-sm text-amber-900">
              작업 권한이 만료돼 다시 받았어. 입력은 그대로 있어 — 제출을 다시 눌러줘.
            </Card>
          )}
          <div className="grid grid-cols-1 gap-2">
            {(['label', 'hold', 'exclude'] as BlindDecision[]).map((dec) => (
              <SelectionCard
                key={dec}
                pressed={decision === dec}
                tone={DECISION_TONES[dec]}
                title={BLIND_DECISION_COPY[dec].title}
                description={BLIND_DECISION_COPY[dec].description}
                onClick={() => setDecision(dec)}
              />
            ))}
          </div>

          {decision === 'exclude' && (
            <Card className="space-y-2">
              <div className="text-sm font-medium text-zinc-800">제외 사유</div>
              <div className="flex flex-wrap gap-2">
                {BLIND_EXCLUDE_REASONS.map((r) => (
                  <SelectionCard
                    key={r.code}
                    pressed={reason === r.code}
                    tone="danger"
                    title={r.label}
                    description=""
                    className="w-auto"
                    onClick={() => setReason(r.code)}
                  />
                ))}
              </div>
            </Card>
          )}

          {decision === 'label' && (
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
              onSave={submit}
              saveLabel="이 판정 제출"
            />
          )}

          {error && <Card className="border-rose-200 bg-rose-50 text-sm text-rose-800">{error}</Card>}

          {decision !== 'label' && decision != null && (
            <Card className="space-y-2">
              <p className="text-xs text-zinc-600">최초 제출은 나중에 내가 수정할 수 없어. 확인하고 제출해줘.</p>
              <Button variant="labelingPrimary" size="lg" className="w-full" disabled={saving || !leaseHeld} onClick={submit}>
                {saving ? '제출 중…' : '이 판정 제출'}
              </Button>
            </Card>
          )}
        </>
      )}
    </main>
  );
}
