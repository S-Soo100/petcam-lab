'use client';

// /labeling/library/[clipId] — 공용 읽기 전용 재생 상세(설계 §5.3·§6). 영상 + 카메라/시각/길이 +
// 라벨 상태/출처. 최종 라벨(decision·GT)은 label_state='final' 일 때만 노출하고, 확정 전에는
// '라벨 확정 중'/'Owner 검수 중' 문구만 보여준다. write control(저장·보류·제외·수정·VLM 검수)은
// 하나도 없다. POST/PATCH/DELETE 를 호출하지 않는다.

import { Suspense, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useParams, useSearchParams } from 'next/navigation';

import Badge from '@/components/ui/Badge';
import { Card } from '@/components/ui/Card';
import { ApiError, UnauthorizedError } from '@/lib/labelingApi';
import { createRequestGeneration } from '@/lib/requestGeneration';
import { formatClipCapturedAt } from '@/lib/labelingV2';
import {
  getLabelingLibraryClip,
  getLibraryFileUrl,
} from '@/lib/motionBlindReviewApi';
import { labelSourceCopy, labelStateCopy, type LabelingLibraryItem } from '@/lib/labelingRoleData';
import { VideoPlayer } from '../../_labeling-forms';

export default function LibraryClipPage() {
  return (
    <Suspense
      fallback={<main className="min-w-0 px-4 py-6 text-sm text-zinc-500">불러오는 중…</main>}
    >
      <LibraryDetailInner />
    </Suspense>
  );
}

function LibraryDetailInner() {
  const { clipId } = useParams<{ clipId: string }>();
  const searchParams = useSearchParams();
  const backHref = searchParams.get('back') || '/labeling/library';

  const [item, setItem] = useState<LabelingLibraryItem | null>(null);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const genRef = useRef(createRequestGeneration());

  useEffect(() => {
    let alive = true;
    const gen = genRef.current;
    const mine = gen.next();
    setLoading(true);
    setErr(null);
    setItem(null);
    setVideoUrl(null); // clip 전환 시 영상 상태 초기화.
    (async () => {
      try {
        const it = await getLabelingLibraryClip(clipId);
        if (!alive || !gen.isCurrent(mine)) return;
        setItem(it);
        // 서명 URL 은 별도로 받는다. 실패해도 메타는 보여준다.
        try {
          const { url } = await getLibraryFileUrl(clipId);
          if (alive && gen.isCurrent(mine)) setVideoUrl(url);
        } catch {
          /* 재생 불가는 상세에서 조용히 안내(메타는 유지) */
        }
      } catch (e) {
        if (!alive || !gen.isCurrent(mine)) return;
        if (e instanceof UnauthorizedError) {
          setErr('로그인이 필요해.');
          return;
        }
        setErr(e instanceof ApiError ? e.message : (e as Error).message);
      } finally {
        if (alive && gen.isCurrent(mine)) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [clipId]);

  if (loading) {
    return <main className="min-w-0 px-4 py-6 text-sm text-zinc-500">불러오는 중…</main>;
  }
  if (err || !item) {
    return (
      <main className="min-w-0 space-y-3 px-4 py-6">
        <Link href={backHref} className="text-sm text-emerald-600 hover:underline">
          ← 목록으로
        </Link>
        <Card className="border-rose-200 bg-rose-50 text-sm text-rose-800">
          {err ?? '영상을 찾을 수 없어.'}
        </Card>
      </main>
    );
  }

  return <LibraryDetailView item={item} videoUrl={videoUrl} backHref={backHref} />;
}

// 순수 상세 뷰(SSR 테스트 대상). 읽기 전용 — 어떤 write control 도 렌더하지 않는다.
export function LibraryDetailView({
  item,
  videoUrl,
  backHref,
}: {
  item: LabelingLibraryItem;
  videoUrl: string | null;
  backHref: string;
}) {
  const isFinal = item.label_state === 'final';
  return (
    <main className="min-w-0 space-y-4 px-4 py-6">
      <div className="flex items-center justify-between gap-2">
        <Link href={backHref} className="text-sm text-emerald-600 hover:underline">
          ← 목록으로
        </Link>
        <Badge tone="neutral">읽기 전용</Badge>
      </div>

      <VideoPlayer src={videoUrl} />

      <Card className="space-y-2 text-sm">
        <div className="font-medium text-zinc-900">{item.camera_name ?? '카메라'}</div>
        <div className="text-xs text-zinc-500">
          {formatClipCapturedAt(item.started_at, item.duration_sec)}
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge tone={isFinal ? 'success' : 'info'}>{labelStateCopy(item.label_state)}</Badge>
          <Badge tone="neutral">{labelSourceCopy(item.label_source)}</Badge>
        </div>

        {isFinal ? (
          <div className="space-y-1">
            {item.final_decision && (
              <div className="text-sm text-zinc-800">최종 판정: {item.final_decision}</div>
            )}
            <FinalGtSummary gt={item.final_gt} />
          </div>
        ) : (
          <div className="text-sm text-zinc-600">{labelStateCopy(item.label_state)}</div>
        )}
      </Card>
    </main>
  );
}

// 최종 GT 요약 — final 일 때만 호출. 대표 행동/구간 수만 짧게. write 폼이 아니다(읽기 전용).
function FinalGtSummary({ gt }: { gt: unknown }) {
  if (!gt || typeof gt !== 'object') return null;
  const record = gt as Record<string, unknown>;
  const primary = record.primary_action ?? record.action;
  const segments = Array.isArray(record.segments) ? record.segments.length : null;
  const parts: string[] = [];
  if (typeof primary === 'string' && primary) parts.push(primary);
  if (segments != null) parts.push(`구간 ${segments}개`);
  if (parts.length === 0) return null;
  return <div className="text-xs text-zinc-600">기록: {parts.join(' · ')}</div>;
}
