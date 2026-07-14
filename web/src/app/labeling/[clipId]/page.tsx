'use client';

// 유저 체험 흐름:
// [영상+GT 폼] 사람이 AI 답을 모른 채 관찰 근거를 기록한다.
// → [GT 잠금] 최초 답은 바뀌지 않고 VLM 원문이 처음 공개된다.
// → [VLM 검수] 정답/부분정답/오답과 오류 원인을 남긴다.
// → [완료] 다음 미라벨 영상으로 이어진다.
//
// 영상 플레이어·GT/VLM 폼은 튜토리얼과 공유하는 _labeling-forms 컴포넌트를 쓴다.
// 저장 API(saveGroundTruth/saveVlmReview)는 production 전용 — 튜토리얼과 분리(설계 §18).

import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { useCallback, useEffect, useMemo, useState } from 'react';

import Badge from '@/components/ui/Badge';
import Button from '@/components/ui/Button';
import { Card, CardTitle } from '@/components/ui/Card';
import { useToast } from '@/components/Toast';
import {
  ApiError,
  UnauthorizedError,
  getClipDownloadUrl,
  getClipFileUrl,
  getLabelingV2,
  getMyLabels,
  getQueue,
  saveGroundTruth,
  saveVlmReview,
  type ClipRow,
  type LabelOut,
} from '@/lib/labelingApi';
import {
  PRIMARY_ACTIONS,
  applyVisibilityChange,
  collectGroundTruthIssues,
  firstIssueField,
  formatClipCapturedAt,
  type GroundTruthField,
  type GroundTruthInput,
  type GroundTruthValidationIssue,
  type LabelingSession,
  type ObservedAction,
  type Visibility,
  type VlmReviewInput,
} from '@/lib/labelingV2';
import {
  GroundTruthForm,
  GtSummary,
  MetadataCard,
  VideoPlayer,
  VlmReviewCard,
  allSelectedFields,
  emptyGt,
  fieldAnchorId,
  freshSegment,
} from '../_labeling-forms';
import { CorrectionPanel } from '../_correction-panel';
import { useIsOwner, useLabelingUserId } from '../_owner-context';
import { useLabelingDraft, type DraftPhase } from '@/lib/labelingDraft';

export default function LabelClipPage() {
  const router = useRouter();
  const { clipId } = useParams<{ clipId: string }>();
  const toast = useToast();
  const isOwner = useIsOwner();
  const [clip, setClip] = useState<ClipRow | null>(null);
  const [session, setSession] = useState<LabelingSession | null>(null);
  const [metadata, setMetadata] = useState<Record<string, unknown>>({});
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [compatLabels, setCompatLabels] = useState<LabelOut[]>([]);
  const [gt, setGt] = useState<GroundTruthInput>(() => emptyGt(60));
  // 어떤 필드를 라벨러가 직접 골랐는지 추적해 기본값 프리셀렉트를 없앤다(설계 §6.1).
  const [selected, setSelected] = useState<Set<GroundTruthField>>(() => new Set());
  const [issues, setIssues] = useState<GroundTruthValidationIssue[]>([]);
  const [review, setReview] = useState<VlmReviewInput>({ verdict: 'correct', error_tags: [], note: null });
  const [busy, setBusy] = useState(true);
  const [saving, setSaving] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // owner 전용 현재 GT 보정(설계 §7).
  const [correcting, setCorrecting] = useState(false);
  const [revisedAt, setRevisedAt] = useState<string | null>(null);

  const duration = useMemo(() => Number(clip?.duration_sec) || 60, [clip]);
  const prediction = session?.prediction_snapshot ?? null;
  const gtLocked = Boolean(session?.initial_gt);
  const completed = session?.stage === 'completed';

  // 저장 전 입력 임시 저장(설계 §9.3 · 하드닝 §3·§4). 사람 판정(gt)·AI 검수(review) 단계 분리.
  const userId = useLabelingUserId();
  const draftPhase: DraftPhase | null = busy
    ? null
    : !gtLocked
      ? 'gt'
      : !completed && prediction
        ? 'review'
        : null;
  const { clearGt, clearReview } = useLabelingDraft({
    userId,
    scope: `clip:${clipId}`,
    phase: draftPhase,
    gt,
    selected,
    review,
    onRestoreGt: (d) => {
      setGt(d.gt);
      setSelected(new Set(d.selected));
    },
    onRestoreReview: (d) => setReview(d.review),
    onRestored: () => toast.show('작성 중인 내용을 복원했어', 'success'),
    onWriteError: () => toast.show('이 브라우저에서 임시 저장하지 못했어', 'error'),
  });

  const load = useCallback(async () => {
    setBusy(true); setError(null);
    try {
      const [state, playback] = await Promise.all([
        getLabelingV2(clipId), getClipFileUrl(clipId),
      ]);
      setClip(state.clip); setSession(state.session); setMetadata(state.system_metadata);
      setVideoUrl(playback.url);
      const saved = state.session?.current_gt ?? state.session?.initial_gt;
      // 저장된 GT 를 다시 열면 모든 필드가 이미 직접 선택된 것으로 본다.
      if (saved) { setGt(saved); setSelected(allSelectedFields()); }
      else { setGt(emptyGt(Number(state.clip.duration_sec) || 60)); setSelected(new Set()); }
      if (state.session?.vlm_verdict) {
        setReview({ verdict: state.session.vlm_verdict, error_tags: state.session.vlm_error_tags,
          note: state.session.vlm_review_note });
      }
    } catch (cause) {
      if (cause instanceof UnauthorizedError) { router.replace('/labeling/login'); return; }
      setError(cause instanceof ApiError ? cause.message : (cause as Error).message);
    } finally { setBusy(false); }
  }, [clipId, router]);

  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    if (!gtLocked) return;
    getMyLabels(clipId).then(setCompatLabels).catch(() => setCompatLabels([]));
  }, [clipId, gtLocked]);

  useEffect(() => {
    if (gtLocked) return;
    const onKeyDown = (event: KeyboardEvent) => {
      const tag = (event.target as HTMLElement | null)?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
      const index = Number(event.key) - 1;
      if (index >= 0 && index < PRIMARY_ACTIONS.length) {
        event.preventDefault(); patchGt('primary_action', PRIMARY_ACTIONS[index]);
      }
      if (event.altKey && event.key === 'Enter' && !saving) {
        event.preventDefault(); void lockGt();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  });

  function patchGt<K extends keyof GroundTruthInput>(key: K, value: GroundTruthInput[K]) {
    setGt((current) => ({ ...current, [key]: value }));
    if (key !== 'note') {
      setSelected((current) => new Set(current).add(key as GroundTruthField));
    }
  }
  // 가시성 변경은 absent 정규화 + highlight 직접선택 해제를 함께 처리한다(하드닝 §6).
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
    const el = document.getElementById(fieldAnchorId(field));
    if (!el) return;
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    el.querySelector<HTMLElement>('button, select, input, textarea')?.focus({ preventScroll: true });
  }

  async function lockGt() {
    // client 가 전체 이슈 목록을 계산하고, 없을 때만 API 를 호출한다(설계 §5.6).
    const localIssues = collectGroundTruthIssues(gt, duration, selected);
    if (localIssues.length > 0) {
      setIssues(localIssues); scrollToFirstIssue(localIssues);
      toast.show('저장 전에 표시된 항목을 채워줘', 'error');
      return;
    }
    setIssues([]);
    setSaving(true); setError(null);
    try {
      const result = await saveGroundTruth(clipId, gt);
      clearGt(); // 사람 판정 저장 성공 → gt 임시본만 삭제(하드닝 §4).
      setSession(result.session);
      if (!result.requires_vlm_review) {
        toast.show('사람 판정 저장 완료 · AI 판정 없음', 'success');
      } else {
        toast.show('사람 판정 저장 완료 · 이제 AI 판정을 검수해', 'success');
      }
    } catch (cause) {
      // server 도 같은 규칙으로 재검증 — issues[] 가 오면 인라인 표시 + 첫 오류로 이동.
      if (cause instanceof ApiError && cause.issues && cause.issues.length > 0) {
        setIssues(cause.issues); scrollToFirstIssue(cause.issues);
      }
      const message = cause instanceof ApiError ? cause.message : (cause as Error).message;
      setError(message); toast.show(`저장 실패: ${message}`, 'error');
    } finally { setSaving(false); }
  }

  async function completeReview() {
    setSaving(true); setError(null);
    try {
      const result = await saveVlmReview(clipId, review);
      clearReview(); // AI 검수 제출 성공 → review 임시본만 삭제(하드닝 §4).
      setSession(result.session); toast.show('검수 완료', 'success');
      await goNext();
    } catch (cause) {
      const message = cause instanceof ApiError ? cause.message : (cause as Error).message;
      setError(message); toast.show(`검수 실패: ${message}`, 'error');
    } finally { setSaving(false); }
  }

  async function goNext() {
    try {
      const queue = await getQueue({ limit: 1 });
      if (queue.items[0]) { router.push(`/labeling/${queue.items[0].id}`); return; }
    } catch { /* 큐 오류면 목록으로 복귀 */ }
    router.push('/labeling');
  }

  async function downloadClip() {
    if (downloading) return;
    setDownloading(true); setError(null);
    try {
      const result = await getClipDownloadUrl(clipId);
      const anchor = document.createElement('a');
      anchor.href = result.url;
      anchor.download = result.filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      toast.show('원본 영상 다운로드를 시작했어', 'success');
    } catch (cause) {
      if (cause instanceof UnauthorizedError) {
        router.replace('/labeling/login');
        return;
      }
      const message = cause instanceof ApiError ? cause.message : (cause as Error).message;
      setError(message);
      toast.show(`다운로드 실패: ${message}`, 'error');
    } finally {
      setDownloading(false);
    }
  }

  async function deleteClip() {
    if (!isOwner || !confirm('이 영상과 관련 라벨을 영구 삭제할까?')) return;
    setSaving(true);
    try {
      const { getSupabaseBrowser } = await import('@/lib/supabaseBrowser');
      const { data } = await getSupabaseBrowser().auth.getSession();
      const response = await fetch(`/api/clips/${clipId}`, {
        method: 'DELETE', headers: { Authorization: `Bearer ${data.session?.access_token ?? ''}` },
      });
      if (!response.ok) {
        // 409(튜토리얼 기준·보정 감사 기록 등)는 서버 메시지를 그대로 보여준다.
        const body = await response.json().catch(() => null);
        throw new Error(body?.error || body?.detail || '삭제하지 못했어.');
      }
      router.push('/labeling');
    } catch (cause) { setError((cause as Error).message); setSaving(false); }
  }

  if (busy) return <main className="mx-auto max-w-6xl px-5 py-8 text-sm text-zinc-500">불러오는 중…</main>;

  return (
    <main className="mx-auto max-w-6xl space-y-5 px-4 py-5 sm:px-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <Link href="/labeling" className="text-xs text-zinc-500 hover:text-zinc-900">← 라벨 대기 큐</Link>
          <h1 className="mt-1 text-xl font-semibold tracking-tight">영상 근거 라벨링</h1>
          {clip && (
            <p className="mt-1 text-sm font-medium tabular-nums text-zinc-700">
              {formatClipCapturedAt(clip.started_at, clip.duration_sec)}
            </p>
          )}
          <p className="mt-1 text-sm text-zinc-500">사람 판정을 먼저 저장한 뒤 같은 화면에서 AI 판정을 확인해.</p>
        </div>
        <div className="flex items-center gap-2">
          <Badge tone={completed ? 'success' : gtLocked ? 'info' : 'warning'}>
            {completed ? '완료' : gtLocked ? '2단계 · AI 판정 확인' : '1단계 · 사람 판정'}
          </Badge>
          <Button
            size="sm"
            variant="secondary"
            onClick={downloadClip}
            disabled={downloading || !clip?.r2_key}
          >
            {downloading ? '준비 중…' : '↓ 영상 다운로드'}
          </Button>
          {isOwner && <Button size="sm" variant="ghost" onClick={deleteClip} disabled={saving}>삭제</Button>}
        </div>
      </header>

      {error && <div className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700 ring-1 ring-red-200">{error}</div>}

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.25fr)_minmax(360px,.75fr)]">
        <section className="space-y-4 lg:sticky lg:top-5 lg:self-start">
          <VideoPlayer src={videoUrl} />
          <MetadataCard metadata={metadata} clipId={clipId} />
        </section>

        <section className="space-y-4">
          {!gtLocked ? (
            <GroundTruthForm gt={gt} duration={duration} saving={saving}
              explicitlySelected={selected} issues={issues}
              patchGt={patchGt} onSelectVisibility={selectVisibility}
              toggleObserved={toggleObserved} updateSegment={updateSegment}
              onSave={lockGt} />
          ) : correcting && isOwner && session ? (
            <>
              <GtSummary gt={session.initial_gt ?? gt} duration={duration} />
              <CorrectionPanel
                clipId={clipId}
                session={session}
                duration={duration}
                onRevised={(result) => {
                  setSession(result.session);
                  setGt(result.session.current_gt ?? gt);
                  setSelected(allSelectedFields());
                  setRevisedAt(result.revised_at);
                  if (result.session.vlm_verdict) {
                    setReview({ verdict: result.session.vlm_verdict, error_tags: result.session.vlm_error_tags,
                      note: result.session.vlm_review_note });
                  }
                  setCorrecting(false);
                }}
                onCancel={() => setCorrecting(false)}
              />
            </>
          ) : (
            <>
              <GtSummary gt={session?.initial_gt ?? gt} duration={duration} />
              {prediction ? (
                <VlmReviewCard prediction={prediction} humanGt={session?.initial_gt ?? gt}
                  review={review} setReview={setReview} saving={saving}
                  completed={completed} onComplete={completeReview} owner={isOwner} />
              ) : (
                <Card className="border-emerald-200 bg-emerald-50">
                  <CardTitle>사람 판정 저장 완료</CardTitle>
                  <p className="mt-2 text-sm text-emerald-800">이 영상에는 AI 판정이 없어 사람 판정만 저장했어.</p>
                </Card>
              )}
              {completed && isOwner && prediction && (
                <Card padding="sm" className="border-amber-200 bg-amber-50">
                  {revisedAt && <p className="mb-1 text-xs text-emerald-800">현재 GT 보정 완료 · {new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', dateStyle: 'short', timeStyle: 'medium' }).format(new Date(revisedAt))}</p>}
                  <p className="text-xs text-amber-800">최초 blind GT는 보존돼. 현재 기준 답만 감사 기록과 함께 보정할 수 있어.</p>
                  <Button size="sm" variant="secondary" className="mt-2" onClick={() => setCorrecting(true)}>현재 GT 보정</Button>
                </Card>
              )}
              {completed && <Button className="w-full" size="lg" onClick={goNext}>다음 영상</Button>}
              {/* 과거 behavior_labels 감사 기록 — raw action·내부 용어라 owner 기술 정보로만 노출한다(하드닝 §7). */}
              {isOwner && compatLabels.length > 0 && <Card padding="sm"><details><summary className="cursor-pointer text-xs font-medium text-zinc-600">기존 behavior_labels 호환 기록 (owner 전용 · {compatLabels.length})</summary>
                <ul className="mt-2 space-y-1 text-xs text-zinc-600">{compatLabels.map((label) => <li key={label.id}>{label.action} · {label.labeled_by.slice(0, 8)} · {label.note || '메모 없음'}</li>)}</ul>
              </details></Card>}
            </>
          )}
        </section>
      </div>
    </main>
  );
}
