'use client';

// 튜토리얼 요약(설계 §6.1·§8). 목적·예상 시간·점수 합격선 없음 안내 + 5개 lesson 상태.
// unavailable 이면 준비 중 화면. 완료/면제면 해설 다시 보기 + 큐로 이동.

import { useCallback, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';

import Badge from '@/components/ui/Badge';
import Button from '@/components/ui/Button';
import { Card, CardTitle } from '@/components/ui/Card';
import {
  ApiError,
  UnauthorizedError,
  getTutorialOverview,
  type TutorialOverview,
} from '@/lib/labelingApi';
import { useLabelingAccess } from '../_owner-context';

const STATE_BADGE: Record<string, { label: string; tone: 'success' | 'info' | 'warning' | 'neutral' }> = {
  completed: { label: '완료', tone: 'success' },
  in_progress: { label: '진행 중', tone: 'info' },
  available: { label: '가능', tone: 'warning' },
  locked: { label: '잠금', tone: 'neutral' },
};

export default function TutorialSummaryPage() {
  const router = useRouter();
  const { refresh } = useLabelingAccess();
  const [data, setData] = useState<TutorialOverview | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      setData(await getTutorialOverview());
    } catch (cause) {
      if (cause instanceof UnauthorizedError) {
        router.replace('/labeling/login');
        return;
      }
      setError(cause instanceof ApiError ? cause.message : (cause as Error).message);
    } finally {
      setBusy(false);
    }
  }, [router]);

  useEffect(() => {
    void load();
  }, [load]);

  function goToQueue() {
    refresh();
    router.push('/labeling');
  }

  if (busy) {
    return <main className="mx-auto max-w-2xl px-5 py-10 text-sm text-zinc-500">불러오는 중…</main>;
  }
  if (error) {
    return (
      <main className="mx-auto max-w-2xl px-5 py-10">
        <Card padding="lg">
          <CardTitle>튜토리얼을 불러오지 못했어</CardTitle>
          <p className="mt-2 text-sm text-zinc-600">{error}</p>
          <Button className="mt-4" onClick={load}>다시 시도</Button>
        </Card>
      </main>
    );
  }
  if (!data) return null;

  const { tutorial, set, lessons } = data;

  if (tutorial.status === 'unavailable') {
    return (
      <main className="mx-auto max-w-2xl px-5 py-10">
        <Card padding="lg" className="border-amber-200 bg-amber-50">
          <CardTitle>튜토리얼 준비 중</CardTitle>
          <p className="mt-2 text-sm text-amber-900">
            아직 연습용 영상이 준비되지 않았어. 관리자에게 문의해줘. 준비되면 여기서 5개
            연습을 마친 뒤 본작업 큐가 열려.
          </p>
        </Card>
      </main>
    );
  }

  const done = tutorial.status === 'completed' || tutorial.status === 'waived';
  const nextPosition =
    lessons.find((l) => l.state === 'available' || l.state === 'in_progress')?.position ?? 1;

  return (
    <main className="mx-auto max-w-2xl space-y-6 px-5 py-8">
      <header className="space-y-2">
        <div className="flex items-center gap-2">
          <h1 className="text-2xl font-semibold tracking-tight text-zinc-900">본작업 전 5개 연습</h1>
          <Badge tone={done ? 'success' : 'warning'}>
            {tutorial.completed_lessons}/{tutorial.total_lessons}
          </Badge>
        </div>
        <p className="text-sm text-zinc-600">
          실제 라벨링과 똑같은 흐름(Blind GT → VLM 검수 → 기준 해설)으로 5개를 검수하면서 기준을
          맞춰봐. 약 15~25분. <strong>점수 합격선은 없어</strong> — 5개 해설을 모두 확인하면 본작업
          큐가 열려.
        </p>
        {set && <p className="text-xs text-zinc-400">{set.title} · {set.version}</p>}
      </header>

      {done ? (
        <Card padding="lg" className="border-emerald-200 bg-emerald-50">
          <CardTitle>
            {tutorial.status === 'waived' ? '튜토리얼 면제됨' : '튜토리얼 완료'}
          </CardTitle>
          <p className="mt-2 text-sm text-emerald-900">
            이제 날짜별 본작업을 시작할 수 있어. 아래에서 해설을 다시 볼 수도 있어.
          </p>
          <div className="mt-4 flex flex-wrap gap-2">
            <Button size="lg" onClick={goToQueue}>라벨 대기 큐로 이동</Button>
            <Button size="lg" variant="secondary" onClick={() => router.push('/labeling/tutorial/1')}>
              해설 다시 보기
            </Button>
          </div>
        </Card>
      ) : (
        <Button size="lg" className="w-full" onClick={() => router.push(`/labeling/tutorial/${nextPosition}`)}>
          {tutorial.status === 'not_started' ? '튜토리얼 시작' : '계속하기'}
        </Button>
      )}

      <ol className="space-y-2">
        {lessons.map((lesson) => {
          const badge = STATE_BADGE[lesson.state] ?? STATE_BADGE.locked;
          const clickable = done || lesson.state !== 'locked';
          return (
            <li key={lesson.position}>
              <button
                type="button"
                disabled={!clickable}
                onClick={() => clickable && router.push(`/labeling/tutorial/${lesson.position}`)}
                className={`flex w-full items-center gap-3 rounded-lg border p-4 text-left transition ${
                  clickable
                    ? 'border-zinc-200 bg-white hover:border-zinc-400'
                    : 'cursor-not-allowed border-zinc-100 bg-zinc-50 opacity-60'
                }`}
              >
                <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-zinc-900 text-sm font-semibold text-white">
                  {lesson.position}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium text-zinc-800">{lesson.title}</span>
                  <span className="block truncate text-xs text-zinc-500">{lesson.learning_objective}</span>
                </span>
                <Badge tone={badge.tone}>{badge.label}</Badge>
              </button>
            </li>
          );
        })}
      </ol>
    </main>
  );
}
