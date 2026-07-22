'use client';

// /labeling/motion — production 기본 전환 전 숨은 v3 preview 큐(설계 §6.1).
// useSearchParams(필터 URL 영속) 는 Suspense 경계가 필요하다(Next.js prerender bailout).

import { Suspense } from 'react';

import MotionQueue from '../_motion-queue';

export default function MotionPreviewPage() {
  return (
    <Suspense
      fallback={
        <main className="mx-auto max-w-4xl px-6 py-8 text-sm text-zinc-500">불러오는 중…</main>
      }
    >
      <MotionQueue />
    </Suspense>
  );
}
