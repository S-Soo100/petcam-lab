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
  formatClipCapturedAt,
  type GroundTruthInput,
  type LabelingSession,
  type ObservedAction,
  type VlmReviewInput,
} from '@/lib/labelingV2';
import {
  GroundTruthForm,
  GtSummary,
  MetadataCard,
  VideoPlayer,
  VlmReviewCard,
  emptyGt,
} from '../_labeling-forms';
import { useIsOwner } from '../_owner-context';

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
  const [review, setReview] = useState<VlmReviewInput>({ verdict: 'correct', error_tags: [], note: null });
  const [busy, setBusy] = useState(true);
  const [saving, setSaving] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const duration = useMemo(() => Number(clip?.duration_sec) || 60, [clip]);
  const prediction = session?.prediction_snapshot ?? null;
  const gtLocked = Boolean(session?.initial_gt);
  const completed = session?.stage === 'completed';

  const load = useCallback(async () => {
    setBusy(true); setError(null);
    try {
      const [state, playback] = await Promise.all([
        getLabelingV2(clipId), getClipFileUrl(clipId),
      ]);
      setClip(state.clip); setSession(state.session); setMetadata(state.system_metadata);
      setVideoUrl(playback.url);
      const saved = state.session?.current_gt ?? state.session?.initial_gt;
      setGt(saved ?? emptyGt(Number(state.clip.duration_sec) || 60));
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
  }
  function toggleObserved(action: ObservedAction) {
    const enabled = gt.observed_actions.includes(action);
    const nextObserved = enabled
      ? gt.observed_actions.filter((item) => item !== action)
      : [...gt.observed_actions, action];
    patchGt('observed_actions', nextObserved);
    patchGt('segments', enabled
      ? gt.segments.filter((segment) => segment.action !== action)
      : [...gt.segments, { action, start_sec: 0, end_sec: duration }]);
    if (!nextObserved.some((item) => item.endsWith('_interaction'))) {
      patchGt('enrichment_object', 'none');
      patchGt('interaction_types', []);
    }
  }
  function updateSegment(action: ObservedAction, key: 'start_sec' | 'end_sec', value: number) {
    patchGt('segments', gt.segments.map((segment) =>
      segment.action === action ? { ...segment, [key]: value } : segment));
  }

  async function lockGt() {
    setSaving(true); setError(null);
    try {
      const result = await saveGroundTruth(clipId, gt);
      setSession(result.session);
      if (!result.requires_vlm_review) {
        toast.show('GT 저장 완료 · VLM 판정 없음', 'success');
      } else {
        toast.show('GT 잠금 완료 · 이제 VLM을 검수해', 'success');
      }
    } catch (cause) {
      const message = cause instanceof ApiError ? cause.message : (cause as Error).message;
      setError(message); toast.show(`저장 실패: ${message}`, 'error');
    } finally { setSaving(false); }
  }

  async function completeReview() {
    setSaving(true); setError(null);
    try {
      const result = await saveVlmReview(clipId, review);
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
      if (!response.ok) throw new Error('삭제하지 못했어.');
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
          <p className="mt-1 text-sm text-zinc-500">사람 GT를 먼저 잠근 뒤 같은 화면에서 VLM 판정을 검수해.</p>
        </div>
        <div className="flex items-center gap-2">
          <Badge tone={completed ? 'success' : gtLocked ? 'info' : 'warning'}>
            {completed ? '완료' : gtLocked ? '2단계 · VLM 검수' : '1단계 · Blind GT'}
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
              patchGt={patchGt} toggleObserved={toggleObserved} updateSegment={updateSegment}
              onSave={lockGt} />
          ) : (
            <>
              <GtSummary gt={session?.initial_gt ?? gt} />
              {prediction ? (
                <VlmReviewCard prediction={prediction} humanGt={session?.initial_gt ?? gt}
                  review={review} setReview={setReview} saving={saving}
                  completed={completed} onComplete={completeReview} />
              ) : (
                <Card className="border-emerald-200 bg-emerald-50">
                  <CardTitle>GT 저장 완료</CardTitle>
                  <p className="mt-2 text-sm text-emerald-800">이 영상에는 VLM 판정이 없어 사람 GT만 저장했어.</p>
                </Card>
              )}
              {completed && <Button className="w-full" size="lg" onClick={goNext}>다음 영상</Button>}
              {compatLabels.length > 0 && <Card padding="sm"><details><summary className="cursor-pointer text-xs font-medium text-zinc-600">기존 behavior_labels 호환 기록 ({compatLabels.length})</summary>
                <ul className="mt-2 space-y-1 text-xs text-zinc-600">{compatLabels.map((label) => <li key={label.id}>{label.action} · {label.labeled_by.slice(0, 8)} · {label.note || '메모 없음'}</li>)}</ul>
              </details></Card>}
            </>
          )}
        </section>
      </div>
    </main>
  );
}
