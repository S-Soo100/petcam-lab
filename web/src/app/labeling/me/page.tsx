'use client';

// /labeling/me — 라벨러 '내 기록'(설계 §5.2). 기존 legacy '내 라벨'(getMyLabeled, 수정 가능)을
// 대체해 본인 blind 제출만 immutable 로 보여준다. useSearchParams 는 Suspense 경계로 감싼다.

import { Suspense } from 'react';

import LabelerHistory from '../_labeler-history';

export default function LabelingMinePage() {
  return (
    <Suspense
      fallback={
        <main className="min-w-0 px-4 py-6 text-sm text-zinc-500">불러오는 중…</main>
      }
    >
      <LabelerHistory />
    </Suspense>
  );
}
