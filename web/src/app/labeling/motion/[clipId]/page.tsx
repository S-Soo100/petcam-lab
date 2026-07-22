'use client';

// /labeling/motion/[clipId] — motion_clip blind GT/검수/보정 상세(설계 §5.2·§7).
//
// 흐름: 상세+서명 URL 로드 → onLoadedMetadata 로 라벨링 활성 → owner 직접 GT 저장(원자적
//   label+gt_locked) → prediction 있으면 검수 폼, 없으면 no_prediction 완료 → 완료 후 owner 보정.
// clip 이 바뀌면 item·media request generation 을 올려 이전 응답을 폐기한다. 영상 실패는
// 재시도 + GT/결정 비활성. GT 잠금 전에는 prediction/evidence 를 화면에 담지 않는다(blind).

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { useParams, useRouter, useSearchParams } from 'next/navigation';

import { ApiError, UnauthorizedError } from '@/lib/labelingApi';
import {
  collectGroundTruthIssues,
  firstIssueField,
  applyVisibilityChange,
  type GroundTruthField,
  type GroundTruthInput,
  type GroundTruthValidationIssue,
  type ObservedAction,
  type Visibility,
  type VlmReviewInput,
} from '@/lib/labelingV2';
import {
  canWriteMotionGt,
  decideMotionDetailPhase,
  motionUndoDecision,
  type MotionClipDetail,
  type MotionDecisionChange,
} from '@/lib/labelingV3';
import {
  completeMotionVlmReview,
  decideMotionClip,
  getMotionClip,
  getMotionClipFileUrl,
  getNextUnreviewedMotionClip,
  lockMotionGt,
  reviseMotionGt,
} from '@/lib/labelingV3Api';
import {
  motionDetailPath,
  motionQueuePath,
  parseMotionQueueFilters,
} from '@/lib/labelingV3QueueClient';
import { createRequestGeneration } from '@/lib/requestGeneration';
import Button from '@/components/ui/Button';
import { Card, CardTitle } from '@/components/ui/Card';
import {
  GroundTruthForm,
  GtSummary,
  VideoPlayer,
  VlmReviewCard,
  allSelectedFields,
  emptyGt,
  fieldAnchorId,
  freshSegment,
} from '../../_labeling-forms';
import { useIsOwner } from '../../_owner-context';
import MotionDecisionControls from '../_motion-decision-controls';
import MotionReviewContinuation from '../_motion-review-continuation';

// hold/skip 결정이면 GT 저장을 막고 이 안내를 보인다. 서버 PT424 도 같은 상태를 뜻하므로
// lockGt catch 에서도 재사용해 사용자 문구를 일치시킨다(설계 §5.1·§5.2).
const DECISION_BLOCKS_GT_MESSAGE =
  '보류/제외 상태에서는 사람 판정을 저장할 수 없어. 먼저 라벨 대상으로 보내기를 눌러줘.';

export default function MotionClipDetailPage() {
  const router = useRouter();
  const { clipId } = useParams<{ clipId: string }>();
  const searchParams = useSearchParams();
  const isOwner = useIsOwner();

  // 목록에서 전달한 필터(state/camera/date/media). 목록 복귀·다음 미분류 영상이 이 문맥을 유지한다(설계 §5·§6).
  const filters = useMemo(
    () => parseMotionQueueFilters(new URLSearchParams(searchParams.toString())),
    [searchParams],
  );

  const [detail, setDetail] = useState<MotionClipDetail | null>(null);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [videoReady, setVideoReady] = useState(false);
  const [videoFailed, setVideoFailed] = useState(false);
  const [gt, setGt] = useState<GroundTruthInput>(() => emptyGt(60));
  const [selected, setSelected] = useState<Set<GroundTruthField>>(() => new Set());
  const [issues, setIssues] = useState<GroundTruthValidationIssue[]>([]);
  const [review, setReview] = useState<VlmReviewInput>({ verdict: 'correct', error_tags: [], note: null });
  const [busy, setBusy] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [correcting, setCorrecting] = useState(false);
  const [reviseReason, setReviseReason] = useState('');

  // 분류 성공 결과(직전/새 상태 + updated_at). 결과 안내 Card·결정 취소(undo)에 쓴다(설계 §7).
  const [decisionChange, setDecisionChange] = useState<MotionDecisionChange | null>(null);
  const [nextBusy, setNextBusy] = useState(false);
  const [nextFailed, setNextFailed] = useState(false);
  const [undoBusy, setUndoBusy] = useState(false);
  // 다음 영상 조회 연속 실패 카운터 — 3회면 목록으로 돌려 새로고침을 유도한다(설계 §7.3).
  const nextAttempts = useRef(0);

  // item·media 두 요청 세대 — clip 이 바뀌면 각각 올려 이전 응답을 폐기한다.
  const itemGen = useRef(createRequestGeneration());
  const mediaGen = useRef(createRequestGeneration());

  const duration = useMemo(() => Number(detail?.duration_sec) || 60, [detail]);
  const phase = detail
    ? decideMotionDetailPhase({ session: detail.session, media_ready: detail.media_ready })
    : null;
  const prediction = (detail?.prediction ?? null) as Record<string, unknown> | null;
  const completed = detail?.session?.stage === 'completed';

  const loadMedia = useCallback(async () => {
    const g = mediaGen.current.next();
    setVideoUrl(null);
    setVideoReady(false);
    setVideoFailed(false);
    try {
      const media = await getMotionClipFileUrl(clipId);
      if (!mediaGen.current.isCurrent(g)) return;
      setVideoUrl(media.url);
    } catch {
      if (!mediaGen.current.isCurrent(g)) return;
      setVideoFailed(true);
    }
  }, [clipId]);

  const load = useCallback(async () => {
    const g = itemGen.current.next();
    setBusy(true);
    setError(null);
    try {
      const d = await getMotionClip(clipId);
      if (!itemGen.current.isCurrent(g)) return;
      setDetail(d);
      const saved = d.session?.current_gt ?? d.session?.initial_gt ?? null;
      if (saved) {
        setGt(saved);
        setSelected(allSelectedFields());
      } else {
        setGt(emptyGt(Number(d.duration_sec) || 60));
        setSelected(new Set());
      }
      if (d.session?.vlm_verdict) {
        setReview({
          verdict: d.session.vlm_verdict,
          error_tags: d.session.vlm_error_tags,
          note: d.session.vlm_review_note,
        });
      }
    } catch (cause) {
      if (!itemGen.current.isCurrent(g)) return;
      if (cause instanceof UnauthorizedError) {
        router.replace('/labeling/login');
        return;
      }
      setError(cause instanceof ApiError ? cause.message : (cause as Error).message);
    } finally {
      if (itemGen.current.isCurrent(g)) setBusy(false);
    }
  }, [clipId, router]);

  useEffect(() => {
    void load();
    void loadMedia();
    return () => {
      itemGen.current.next();
      mediaGen.current.next();
    };
  }, [load, loadMedia]);

  // 다음 영상으로 이동하면 같은 route 의 clipId 만 바뀌므로(컴포넌트 재사용) 결과 안내 상태를 초기화한다.
  useEffect(() => {
    setDecisionChange(null);
    setNextFailed(false);
    nextAttempts.current = 0;
  }, [clipId]);

  // 현재 필터의 다음 미분류 영상으로 이동한다. 없으면 완료 안내와 함께 목록으로 돌아간다(설계 §7.2).
  // 자동으로 넘어가지 않고 사용자가 버튼을 눌렀을 때만 호출된다.
  const goNext = useCallback(async () => {
    setNextBusy(true);
    setNextFailed(false);
    try {
      const { next_clip_id } = await getNextUnreviewedMotionClip(clipId, filters);
      nextAttempts.current = 0;
      if (next_clip_id) {
        router.push(motionDetailPath(next_clip_id, filters));
      } else {
        router.push(motionQueuePath(filters, { reviewComplete: true }));
      }
    } catch (cause) {
      if (cause instanceof UnauthorizedError) {
        router.replace('/labeling/login');
        return;
      }
      // 저장된 분류는 되돌리지 않는다. 3회 연속 실패면 목록으로 돌려 새로고침을 유도한다(설계 §7.3).
      nextAttempts.current += 1;
      if (nextAttempts.current >= 3) {
        nextAttempts.current = 0;
        router.push(motionQueuePath(filters));
        return;
      }
      setNextFailed(true);
    } finally {
      setNextBusy(false);
    }
  }, [clipId, filters, router]);

  // 결정 취소 — 직전 상태로 되돌린다. current updatedAt 을 expected 로 보내 경합을 막는다(설계 §7.2·§7.3).
  const undoDecision = useCallback(async () => {
    if (!decisionChange) return;
    const decision = motionUndoDecision(decisionChange.previous);
    setUndoBusy(true);
    setError(null);
    try {
      const result = await decideMotionClip(clipId, {
        decision,
        expected_updated_at: decisionChange.updatedAt,
      });
      setDetail((d) => (d ? { ...d, state: result.state, state_updated_at: result.updated_at } : d));
      setDecisionChange(null);
      setNextFailed(false);
    } catch (cause) {
      if (cause instanceof ApiError && cause.code === 'stale_state') {
        // undo 경합: 다른 화면에서 상태가 바뀜 → 최신 detail 을 다시 읽어 알린다.
        setError('다른 화면에서 상태가 바뀌었어. 최신 상태를 다시 불러왔어.');
        setDecisionChange(null);
        await load();
      } else {
        setError(cause instanceof ApiError ? cause.message : (cause as Error).message);
      }
    } finally {
      setUndoBusy(false);
    }
  }, [clipId, decisionChange, load]);

  // label 상태의 "지금 사람 판정 작성" — GT 폼 첫 항목으로 스크롤한다.
  function scrollToGtForm() {
    document
      .getElementById(fieldAnchorId('visibility'))
      ?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  // ── GT 폼 핸들러(v2 계약과 동일 의미) ──────────────────────────
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
  function scrollToFirstIssue(list: GroundTruthValidationIssue[]) {
    const field = firstIssueField(list);
    if (!field) return;
    const el = document.getElementById(fieldAnchorId(field));
    if (!el) return;
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    el.querySelector<HTMLElement>('button, select, input, textarea')?.focus({ preventScroll: true });
  }

  async function lockGt() {
    const local = collectGroundTruthIssues(gt, duration, selected);
    if (local.length > 0) {
      setIssues(local);
      scrollToFirstIssue(local);
      return;
    }
    setIssues([]);
    setSaving(true);
    setError(null);
    try {
      await lockMotionGt(clipId, gt);
      await load(); // 잠금 후 세션·prediction 을 다시 읽어 review/complete 로 전환.
    } catch (cause) {
      if (cause instanceof ApiError && cause.issues) {
        setIssues(cause.issues);
        scrollToFirstIssue(cause.issues);
      } else if (cause instanceof ApiError && cause.code === 'decision_blocks_labeling') {
        // 오래 열린 탭이 hold/skip 결정 뒤에도 GT 를 저장하려다 DB guard(PT424)에 막힌 경우.
        // 같은 안내 문구를 보이고 detail 을 다시 읽어 폼이 잠긴 최신 상태로 복구한다.
        setError(DECISION_BLOCKS_GT_MESSAGE);
        await load();
      } else {
        setError(cause instanceof ApiError ? cause.message : (cause as Error).message);
      }
    } finally {
      setSaving(false);
    }
  }

  async function completeReview(withVerdict: boolean) {
    setSaving(true);
    setError(null);
    try {
      await completeMotionVlmReview(
        clipId,
        withVerdict ? { verdict: review.verdict, error_tags: review.error_tags, note: review.note } : undefined,
      );
      await load();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : (cause as Error).message);
    } finally {
      setSaving(false);
    }
  }

  async function saveRevision() {
    if (reviseReason.trim().length < 10) {
      setError('보정 사유를 10자 이상 적어줘.');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await reviseMotionGt(clipId, { gt, reason: reviseReason.trim() });
      setCorrecting(false);
      setReviseReason('');
      await load();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : (cause as Error).message);
    } finally {
      setSaving(false);
    }
  }

  const startedAt = detail
    ? new Date(detail.started_at).toLocaleString('ko-KR', { timeZone: 'Asia/Seoul', hour12: false })
    : '';
  // 영상 준비 전/실패면 GT 저장을 막고(설계 §5.2), hold/skip 결정이면 GT 입력도 잠근다(설계 §5.1).
  const canWriteGt = !!detail && canWriteMotionGt(detail.state);
  const actionsEnabled = videoReady && !videoFailed && canWriteGt;

  return (
    <main className="mx-auto max-w-3xl space-y-5 px-6 py-8">
      <div className="flex items-center justify-between gap-3">
        <Link
          href={motionQueuePath(filters)}
          prefetch={false}
          className="text-sm text-zinc-500 hover:text-zinc-800"
        >
          ← 목록
        </Link>
        {detail && <span className="text-sm tabular-nums text-zinc-600">{startedAt} · {detail.camera_name}</span>}
      </div>

      {busy && <p className="text-sm text-zinc-500">불러오는 중…</p>}
      {error && (
        <div className="rounded-md bg-red-50 px-4 py-3 text-sm text-red-700 ring-1 ring-inset ring-red-200">
          {error}
        </div>
      )}

      {detail && (
        <>
          {detail.media_ready ? (
            <>
              <VideoPlayer
                src={videoUrl}
                onLoadedMetadata={() => setVideoReady(true)}
                onError={() => setVideoFailed(true)}
              />
              {videoFailed && (
                <div className="flex items-center gap-3 rounded-md bg-amber-50 px-4 py-2 text-sm text-amber-800 ring-1 ring-inset ring-amber-200">
                  영상을 재생하지 못했어. 라벨링·분류가 비활성화됐어.
                  <Button variant="secondary" size="sm" onClick={() => void loadMedia()}>
                    재시도
                  </Button>
                </div>
              )}
            </>
          ) : (
            <Card padding="lg">
              <p className="text-sm text-zinc-600">원본 영상이 없어 재생할 수 없어. 라벨링·분류가 비활성화돼.</p>
            </Card>
          )}

          {isOwner && detail.media_ready && (
            <MotionDecisionControls
              clipId={clipId}
              state={detail.state}
              stateUpdatedAt={detail.state_updated_at}
              onDecided={(change) => {
                // 강제 탭 이동 없이 상세에 머문다. 결과 안내·다음 영상은 continuation Card 로(설계 §7).
                setDetail((d) =>
                  d ? { ...d, state: change.next, state_updated_at: change.updatedAt } : d,
                );
                // reset(→unreviewed)은 결과 안내가 없다. label/hold/skip 만 Card 를 띄운다.
                setDecisionChange(change.next === 'unreviewed' ? null : change);
                setNextFailed(false);
              }}
            />
          )}

          {/* 분류 결과 확인 + 결정 취소 + 다음 미분류 영상(설계 §7.2). gt 단계에서만(잠금 전) 노출한다. */}
          {isOwner && detail.media_ready && phase === 'gt' && decisionChange && (
            <MotionReviewContinuation
              state={decisionChange.next}
              nextBusy={nextBusy}
              nextFailed={nextFailed}
              undoBusy={undoBusy}
              onUndo={() => void undoDecision()}
              onNext={() => void goNext()}
              onWriteGtNow={scrollToGtForm}
            />
          )}

          {/* hold/skip 은 GT 저장이 막혀 있으니 이유와 복구 방법을 안내한다(설계 §5.1). */}
          {detail.media_ready && !canWriteMotionGt(detail.state) && (
            <Card className="border-amber-200 bg-amber-50">
              <p className="text-sm text-amber-800">{DECISION_BLOCKS_GT_MESSAGE}</p>
            </Card>
          )}

          {/* phase 별 화면. hold/skip 은 GT 폼을 아예 렌더하지 않는다(설계 §7.1) — canWriteMotionGt 가 false. */}
          {phase === 'gt' && canWriteMotionGt(detail.state) && (
            <fieldset disabled={!actionsEnabled} className={actionsEnabled ? '' : 'opacity-60'}>
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
                onSave={lockGt}
              />
            </fieldset>
          )}

          {phase === 'review' && (
            <>
              <GtSummary gt={gt} duration={duration} />
              {prediction ? (
                <VlmReviewCard
                  prediction={prediction}
                  humanGt={gt}
                  review={review}
                  setReview={setReview}
                  saving={saving}
                  completed={false}
                  onComplete={() => completeReview(true)}
                  owner={isOwner}
                />
              ) : (
                <Card className="space-y-3">
                  <CardTitle>AI 판정 없음</CardTitle>
                  <p className="text-sm text-zinc-600">이 영상엔 성공한 AI 판정이 없어. 사람 판정만 기록하고 완료해.</p>
                  <Button size="lg" className="w-full" disabled={saving} onClick={() => completeReview(false)}>
                    {saving ? '저장 중…' : '완료 (AI 판정 없음)'}
                  </Button>
                </Card>
              )}
            </>
          )}

          {phase === 'complete' && (
            <>
              <GtSummary gt={gt} duration={duration} />
              {prediction && (
                <VlmReviewCard
                  prediction={prediction}
                  humanGt={gt}
                  review={review}
                  setReview={setReview}
                  saving={saving}
                  completed
                  onComplete={() => {}}
                  owner={isOwner}
                />
              )}
              {isOwner && !correcting && (
                <Button variant="secondary" size="sm" onClick={() => setCorrecting(true)}>
                  GT 보정 (owner)
                </Button>
              )}
              {isOwner && correcting && (
                <Card className="space-y-3">
                  <CardTitle>기준 GT 보정</CardTitle>
                  <p className="text-xs text-zinc-500">최초 blind 판정(initial_gt)은 바뀌지 않고, 현재 GT만 사유와 함께 보정돼.</p>
                  <fieldset disabled={!actionsEnabled} className={actionsEnabled ? '' : 'opacity-60'}>
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
                      onSave={() => {}}
                      saveLabel="(아래 사유 입력 후 보정 저장)"
                    />
                  </fieldset>
                  <label className="block text-sm font-medium">
                    보정 사유 (10자 이상)
                    <textarea
                      value={reviseReason}
                      onChange={(e) => setReviseReason(e.target.value)}
                      maxLength={500}
                      className="mt-2 min-h-16 w-full rounded-lg border border-zinc-300 p-3 font-normal"
                    />
                  </label>
                  <div className="flex gap-2">
                    <Button size="sm" disabled={saving} onClick={saveRevision}>
                      {saving ? '저장 중…' : '보정 저장'}
                    </Button>
                    <Button variant="secondary" size="sm" disabled={saving} onClick={() => setCorrecting(false)}>
                      취소
                    </Button>
                  </div>
                </Card>
              )}
              {/* 라벨링을 마친 뒤에도 현재 필터의 다음 미분류 영상으로 이어서 검수한다(설계 §3.4·§7.2). */}
              {isOwner && (
                <div className="pt-1">
                  <Button
                    variant="primary"
                    size="sm"
                    disabled={nextBusy}
                    onClick={() => void goNext()}
                  >
                    {nextBusy ? '이동 중…' : '다음 미분류 영상'}
                  </Button>
                  {nextFailed && (
                    <p className="mt-2 text-xs text-amber-700">
                      다음 영상을 찾지 못했어.
                      <button
                        type="button"
                        className="ml-1 underline"
                        disabled={nextBusy}
                        onClick={() => void goNext()}
                      >
                        다시 찾기
                      </button>
                    </p>
                  )}
                </div>
              )}
            </>
          )}
        </>
      )}
    </main>
  );
}
