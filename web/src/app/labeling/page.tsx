// /labeling 역할별 landing(설계 §3.2). 승인 라벨러는 '오늘 작업' 큐, Owner 는 운영 현황으로
// 이동한다(HomeSwitch 가 access 로 가른다). legacy/motion 운영 큐는 더 이상 홈 기본값이 아니며
// Owner 의 '직접 라벨링'(/labeling/motion)·'연구 도구'(/labeling/owner/research) 로만 진입한다.
// resolveLabelingQueueSource(env) 는 그 직접 라벨링 경로에서 계속 쓰므로 유지한다.

import { Suspense } from 'react';

import HomeSwitch from './_home-switch';

export default function LabelingPage() {
  return (
    <Suspense
      fallback={
        <main className="mx-auto max-w-4xl px-6 py-8 text-sm text-zinc-500">불러오는 중…</main>
      }
    >
      <HomeSwitch />
    </Suspense>
  );
}
