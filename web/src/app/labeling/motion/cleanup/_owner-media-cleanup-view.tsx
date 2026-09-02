'use client';

import { useCallback, useEffect, useState } from 'react';

import ReviewVideo from '../../_review-video';
import Button from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { ApiError } from '@/lib/labelingApi';
import type {
  OwnerCleanupDecision,
  OwnerCleanupItem,
  OwnerCleanupSummary,
} from '@/lib/rbaOwnerMediaCleanup';
import {
  decideOwnerCleanup,
  getOwnerCleanupMediaUrl,
  getOwnerCleanupWorkspace,
} from '@/lib/rbaOwnerMediaCleanupApi';

function formatKst(iso: string): string {
  return new Date(iso).toLocaleString('ko-KR', { timeZone: 'Asia/Seoul' });
}
export function OwnerMediaCleanupView({
  item,
  videoUrl,
  summary,
  busy,
  onDecision,
  getDownload,
}: {
  item: OwnerCleanupItem | null;
  videoUrl: string | null;
  summary: OwnerCleanupSummary;
  busy: boolean;
  onDecision: (decision: OwnerCleanupDecision) => void;
  getDownload: () => Promise<{ url: string; filename: string }>;
}) {
  if (!item) {
    return (
      <Card padding="lg">
        <h1 className="text-lg font-semibold">초기 영상 정리</h1>
        <p className="mt-2 text-sm text-zinc-600">현재 검수할 영상을 모두 끝냈어.</p>
        <p className="mt-1 text-xs text-zinc-500">완료 {summary.completed} · 파일 없음 {summary.source_missing}</p>
      </Card>
    );
  }
  return (
    <section className="flex flex-col gap-4">
      <header>
        <h1 className="text-xl font-bold text-zinc-950">초기 영상 정리</h1>
        <p className="mt-1 text-sm text-zinc-600">
          게코가 실제로 보이고 활동한 영상인지 확인해. 제출한 답은 바꿀 수 없어.
        </p>
        <p className="mt-2 text-sm font-semibold tabular-nums text-emerald-800">
          {summary.completed} / {summary.available} 완료 · 남음 {summary.remaining}
        </p>
      </header>

      <Card padding="sm">
        <div className="mb-2 flex flex-wrap justify-between gap-2 text-xs text-zinc-500">
          <span>{item.camera_name || '카메라 미상'}</span>
          <span>{formatKst(item.started_at)} · {item.duration_sec.toFixed(1)}초</span>
        </div>
        {videoUrl ? (
          <ReviewVideo src={videoUrl} getDownload={getDownload} />
        ) : (
          <div className="grid aspect-video place-items-center rounded-lg bg-zinc-900 text-sm text-white">
            영상을 불러오는 중…
          </div>
        )}
      </Card>

      <div className="grid gap-3">
        <Card className="border-emerald-200 bg-emerald-50" padding="sm">
          <p className="mb-2 text-sm font-semibold text-emerald-950">남길 영상</p>
          <Button className="w-full" variant="labelingPrimary" disabled={busy} onClick={() => onDecision('keep')}>
            정상 영상으로 남기기
          </Button>
        </Card>

        <Card className="border-rose-200 bg-rose-50" padding="sm">
          <p className="mb-2 text-sm font-semibold text-rose-950">삭제 후보로 분류</p>
          <div className="grid gap-2 sm:grid-cols-2">
            <Button variant="labelingDanger" disabled={busy} onClick={() => onDecision('delete_gecko_absent')}>
              게코가 안 보임
            </Button>
            <Button variant="labelingDanger" disabled={busy} onClick={() => onDecision('delete_no_activity')}>
              게코 활동이 없음
            </Button>
          </div>
          <p className="mt-2 text-xs text-rose-700">이 버튼은 즉시 삭제가 아니라 Owner 삭제 후보 기록이야.</p>
        </Card>

        <Card className="border-amber-200 bg-amber-50" padding="sm">
          <p className="mb-2 text-sm font-semibold text-amber-950">확실하지 않음</p>
          <Button className="w-full" variant="labelingSecondary" disabled={busy} onClick={() => onDecision('uncertain')}>
            판단 보류
          </Button>
        </Card>
      </div>
    </section>
  );
}

export default function OwnerMediaCleanup() {
  const [item, setItem] = useState<OwnerCleanupItem | null>(null);
  const [summary, setSummary] = useState<OwnerCleanupSummary>({ available: 0, completed: 0, remaining: 0, source_missing: 0 });
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const workspace = await getOwnerCleanupWorkspace();
      setItem(workspace.item);
      setSummary(workspace.summary);
      setVideoUrl(null);
      if (workspace.item) {
        const media = await getOwnerCleanupMediaUrl(workspace.item.clip_id);
        setVideoUrl(media.url);
      }
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : '정리 영상을 불러오지 못했어.');
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const decide = useCallback(async (decision: OwnerCleanupDecision) => {
    if (!item || busy) return;
    setBusy(true);
    setError(null);
    try {
      await decideOwnerCleanup(item.clip_id, decision);
      await load();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : '판정을 저장하지 못했어.');
      setBusy(false);
    }
  }, [busy, item, load]);

  return (
    <main className="mx-auto flex max-w-5xl flex-col gap-4 px-4 py-6">
      {error && <div className="rounded-md bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}
      <OwnerMediaCleanupView
        item={item}
        videoUrl={videoUrl}
        summary={summary}
        busy={busy}
        onDecision={(decision) => void decide(decision)}
        getDownload={async () => {
          if (!item) throw new Error('no cleanup item');
          const result = await getOwnerCleanupMediaUrl(item.clip_id, true);
          return { url: result.url, filename: result.filename ?? `petcam-cleanup-${item.clip_id}.mp4` };
        }}
      />
    </main>
  );
}
