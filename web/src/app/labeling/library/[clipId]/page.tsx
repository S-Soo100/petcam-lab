'use client';

// /labeling/library/[clipId] — 공용 읽기 전용 재생 상세(설계 §5.3·§6). 영상 + 카메라/시각/길이 +
// 라벨 상태/출처. 최종 라벨(decision·GT)은 label_state='final' 일 때만 노출하고, 확정 전에는
// '라벨 확정 중'/'Owner 검수 중' 문구만 보여준다. write control(저장·보류·제외·수정·VLM 검수)은
// 하나도 없다. POST/PATCH/DELETE 를 호출하지 않는다.

import { Suspense, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useParams, useSearchParams } from 'next/navigation';

import { Card } from '@/components/ui/Card';
import { ApiError, UnauthorizedError } from '@/lib/labelingApi';
import { createRequestGeneration } from '@/lib/requestGeneration';
import {
  getLabelingLibraryClip,
  getLibraryDownloadUrl,
  getLibraryFileUrl,
} from '@/lib/motionBlindReviewApi';
import type { LabelingLibraryItem } from '@/lib/labelingRoleData';
import { LibraryDetailView } from './_library-detail-view';

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

  return <LibraryDetailView item={item} videoUrl={videoUrl} backHref={backHref}
    getDownload={() => getLibraryDownloadUrl(clipId)} />;
}
