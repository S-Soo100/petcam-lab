'use client';

// 튜토리얼 lesson 상태 머신(설계 §6.2·§8). production 상세와 같은 흐름을 공유 컴포넌트로
// 재현하되 저장 API 는 튜토리얼 전용. 정답/해설은 서버가 stage 에 따라서만 내려준다.
//
// draft            → GroundTruthForm (GT 잠그고 VLM 보기)
// gt_locked        → GtSummary + VlmReviewCard (검수 제출하고 해설 보기)
// review_submitted → GtSummary + TutorialFeedback (해설 확인하고 다음)
// completed        → GtSummary + TutorialFeedback(읽기전용) + 다음

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
  acknowledgeTutorialLesson,
  getTutorialFileUrl,
  getTutorialLesson,
  saveTutorialGt,
  saveTutorialVlmReview,
  type TutorialLessonView,
} from '@/lib/labelingApi';
import {
  PRIMARY_ACTIONS,
  type GroundTruthInput,
  type ObservedAction,
  type VlmReviewInput,
} from '@/lib/labelingV2';
import {
  GroundTruthForm,
  GtSummary,
  VideoPlayer,
  VlmReviewCard,
  emptyGt,
} from '../../_labeling-forms';
import { TutorialFeedback } from '../_tutorial-feedback';
import { useLabelingAccess } from '../../_owner-context';

const TOTAL = 5;

export default function TutorialLessonPage() {
  const router = useRouter();
  const { refresh } = useLabelingAccess();
  const toast = useToast();
  const params = useParams<{ position: string }>();
  const position = Number(params.position);

  const [lesson, setLesson] = useState<TutorialLessonView | null>(null);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [gt, setGt] = useState<GroundTruthInput>(() => emptyGt(60));
  const [review, setReview] = useState<VlmReviewInput>({ verdict: 'correct', error_tags: [], note: null });
  const [busy, setBusy] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const stage = lesson?.attempt?.stage ?? 'draft';
  const prediction = lesson?.prediction_snapshot ?? null;
  const duration = useMemo(() => Number(lesson?.clip.duration_sec) || 60, [lesson]);
  const lockedGt = lesson?.attempt?.submitted_gt ?? gt;

  const load = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const [view, playback] = await Promise.all([
        getTutorialLesson(position),
        getTutorialFileUrl(position),
      ]);
      setLesson(view);
      setVideoUrl(playback.url);
      setGt(view.attempt?.submitted_gt ?? emptyGt(Number(view.clip.duration_sec) || 60));
      if (view.attempt?.submitted_vlm_review) setReview(view.attempt.submitted_vlm_review);
    } catch (cause) {
      if (cause instanceof UnauthorizedError) {
        router.replace('/labeling/login');
        return;
      }
      // 순서 건너뛰기(409)·없음(404) 은 요약으로 되돌려 올바른 위치를 고르게 한다.
      if (cause instanceof ApiError && (cause.status === 409 || cause.status === 404)) {
        router.replace('/labeling/tutorial');
        return;
      }
      setError(cause instanceof ApiError ? cause.message : (cause as Error).message);
    } finally {
      setBusy(false);
    }
  }, [position, router]);

  useEffect(() => {
    if (Number.isInteger(position) && position >= 1 && position <= TOTAL) void load();
    else router.replace('/labeling/tutorial');
  }, [load, position, router]);

  // draft 단계에서만 숫자 단축키(대표 행동)·⌥↵(잠금).
  useEffect(() => {
    if (stage !== 'draft') return;
    const onKeyDown = (event: KeyboardEvent) => {
      const tag = (event.target as HTMLElement | null)?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
      const index = Number(event.key) - 1;
      if (index >= 0 && index < PRIMARY_ACTIONS.length) {
        event.preventDefault();
        patchGt('primary_action', PRIMARY_ACTIONS[index]);
      }
      if (event.altKey && event.key === 'Enter' && !saving) {
        event.preventDefault();
        void lockGt();
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
    setSaving(true);
    setError(null);
    try {
      await saveTutorialGt(position, gt);
      await load();
      toast.show('GT 잠금 완료 · 이제 VLM을 검수해', 'success');
    } catch (cause) {
      const message = cause instanceof ApiError ? cause.message : (cause as Error).message;
      setError(message);
      toast.show(`저장 실패: ${message}`, 'error');
    } finally {
      setSaving(false);
    }
  }

  async function submitReview() {
    setSaving(true);
    setError(null);
    try {
      await saveTutorialVlmReview(position, review);
      await load();
      toast.show('검수 제출 완료 · 해설을 확인해', 'success');
    } catch (cause) {
      const message = cause instanceof ApiError ? cause.message : (cause as Error).message;
      setError(message);
      toast.show(`제출 실패: ${message}`, 'error');
    } finally {
      setSaving(false);
    }
  }

  async function acknowledge() {
    setSaving(true);
    setError(null);
    try {
      const { tutorial_completed } = await acknowledgeTutorialLesson(position);
      if (tutorial_completed || position >= TOTAL) {
        refresh();
        router.push('/labeling/tutorial');
        return;
      }
      router.push(`/labeling/tutorial/${position + 1}`);
    } catch (cause) {
      const message = cause instanceof ApiError ? cause.message : (cause as Error).message;
      setError(message);
      toast.show(`진행 실패: ${message}`, 'error');
    } finally {
      setSaving(false);
    }
  }

  if (busy) {
    return <main className="mx-auto max-w-6xl px-5 py-8 text-sm text-zinc-500">불러오는 중…</main>;
  }
  if (!lesson) return null;

  return (
    <main className="mx-auto max-w-6xl space-y-5 px-4 py-5 sm:px-6">
      <header className="space-y-2">
        <Link href="/labeling/tutorial" className="text-xs text-zinc-500 hover:text-zinc-900">← 튜토리얼 요약</Link>
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="info">{position}/{TOTAL}</Badge>
          <h1 className="text-xl font-semibold tracking-tight">{lesson.title}</h1>
          <Badge tone={stage === 'completed' ? 'success' : stage === 'draft' ? 'warning' : 'info'}>
            {stage === 'completed' ? '완료' : stage === 'draft' ? '1단계 · Blind GT' : stage === 'gt_locked' ? '2단계 · VLM 검수' : '해설'}
          </Badge>
        </div>
        <p className="text-sm text-zinc-600">{lesson.learning_objective}</p>
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-zinc-200">
          <div className="h-full rounded-full bg-emerald-500 transition-all" style={{ width: `${(position / TOTAL) * 100}%` }} />
        </div>
      </header>

      {error && <div className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700 ring-1 ring-red-200">{error}</div>}

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.25fr)_minmax(360px,.75fr)]">
        <section className="space-y-4 lg:sticky lg:top-5 lg:self-start">
          <VideoPlayer src={videoUrl} />
          {stage === 'draft' && lesson.pre_submit_tip && (
            <Card padding="sm" className="border-sky-200 bg-sky-50">
              <p className="text-xs text-sky-900">💡 {lesson.pre_submit_tip}</p>
            </Card>
          )}
        </section>

        <section className="space-y-4">
          {stage === 'draft' ? (
            <GroundTruthForm
              gt={gt}
              duration={duration}
              saving={saving}
              patchGt={patchGt}
              toggleObserved={toggleObserved}
              updateSegment={updateSegment}
              onSave={lockGt}
              saveLabel="GT 잠그고 VLM 보기 (⌥↵)"
            />
          ) : (
            <>
              <GtSummary gt={lockedGt} />
              {stage === 'gt_locked' && prediction && (
                <VlmReviewCard
                  prediction={prediction}
                  humanGt={lockedGt}
                  review={review}
                  setReview={setReview}
                  saving={saving}
                  completed={false}
                  onComplete={submitReview}
                  completeLabel="검수 제출하고 해설 보기"
                />
              )}
              {(stage === 'review_submitted' || stage === 'completed') && lesson.comparison && lesson.feedback && (
                <>
                  <TutorialFeedback comparison={lesson.comparison} feedback={lesson.feedback} />
                  <Button size="lg" className="w-full" disabled={saving} onClick={acknowledge}>
                    {saving ? '처리 중…' : position >= TOTAL ? '해설 확인하고 완료' : '해설 확인하고 다음'}
                  </Button>
                </>
              )}
            </>
          )}
        </section>
      </div>
    </main>
  );
}
