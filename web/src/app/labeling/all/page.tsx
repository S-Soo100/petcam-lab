import { Suspense } from 'react';

import V4ClipList from '../_v4-clip-list';

// B 페이지 — 전체 카메라 목록(v4 스펙 §2 In 4). useSearchParams 때문에 Suspense 경계 필수.
export default function AllPage() {
  return (
    <Suspense fallback={<main className="px-4 py-6 text-sm text-zinc-500">불러오는 중…</main>}>
      <V4ClipList scope="all" basePath="/labeling/all" title="전체" />
    </Suspense>
  );
}
