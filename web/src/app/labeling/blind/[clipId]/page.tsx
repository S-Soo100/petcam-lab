'use client';

import { Suspense } from 'react';
import { useParams, useSearchParams } from 'next/navigation';

import { BlindReviewDetail } from '../../_blind-review-detail';

// live 상세 = /labeling/blind/[clipId]?activity_day=YYYY-MM-DD. cohort_id 는 붙지 않는다(live scope).
function Inner() {
  const { clipId } = useParams<{ clipId: string }>();
  const searchParams = useSearchParams();
  return (
    <BlindReviewDetail
      clipId={clipId}
      cohortId={null}
      activityDay={searchParams.get('activity_day')}
    />
  );
}

export default function BlindClipDetailPage() {
  // useSearchParams 는 prerender bailout → Suspense 경계 필수(메모리 nextjs-usesearchparams-suspense).
  return (
    <Suspense fallback={<main className="mx-auto max-w-3xl px-4 py-6 text-sm text-zinc-500">불러오는 중…</main>}>
      <Inner />
    </Suspense>
  );
}
