// /labeling 기본 소스 wrapper (2026-07-22 v3 전환 게이트).
//
// LABELING_QUEUE_SOURCE=motion 이면 motion_clips v3 큐, 그 외/미설정이면 legacy camera_clips 큐.
// 코드 기본값은 항상 legacy — production 전환은 이 handoff 밖(명시 승인 후 preview env 로만).
// server 컴포넌트가 env 를 읽어 client 큐를 고르고, useSearchParams(필터 URL) 는 Suspense 로 감싼다.

import { Suspense } from 'react';

import { resolveLabelingQueueSource } from '@/lib/labelingV3';
import LegacyQueue from './_legacy-queue';
import MotionQueue from './_motion-queue';

export default function LabelingPage() {
  const source = resolveLabelingQueueSource(process.env.LABELING_QUEUE_SOURCE);
  return (
    <Suspense
      fallback={
        <main className="mx-auto max-w-4xl px-6 py-8 text-sm text-zinc-500">불러오는 중…</main>
      }
    >
      {source === 'motion' ? <MotionQueue /> : <LegacyQueue />}
    </Suspense>
  );
}
