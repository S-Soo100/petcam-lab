'use client';

// /labeling/motion/auto-excluded — Owner 짧은 영상 자동 제외 검수·복구(설계 §4·§6.3).
//
// 권한 경계는 두 겹이다: (1) labeling layout/role shell 이 비-owner 를 리다이렉트하고,
// (2) API(system-exclusions·restore)가 requireOwner 로 서버 최종 경계를 지킨다. 이 페이지는 UI 만.
// AutoExcludedList 가 useState/useEffect 로 데이터를 가져오므로 Suspense 로 감싼다(motion 큐와 동일).

import { Suspense } from 'react';

import AutoExcludedList from './_auto-excluded-list';

export default function AutoExcludedPage() {
  return (
    <Suspense
      fallback={
        <main className="mx-auto max-w-3xl px-4 py-6 text-sm text-zinc-500">불러오는 중…</main>
      }
    >
      <AutoExcludedList />
    </Suspense>
  );
}
