'use client';

// /labeling 홈 스위치(설계 §3.2·§4). 승인 라벨러는 이중 블라인드 '오늘 작업' 큐를 본다.
// Owner 는 기본 홈이 운영 현황(/labeling/owner)이므로 여기서 명시적으로 이동한다 — 라벨링은
// 운영 현황의 '직접 라벨링' 보조 버튼으로만 진입한다(설계 §3.2). pending/rejected 는 layout
// 가드가 이미 대기 화면으로 라우팅하므로 여기서는 null.

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';

import { useLabelingAccess } from './_owner-context';
import BlindReviewQueue from './_blind-review-queue';

function OwnerHomeRedirect() {
  const router = useRouter();
  useEffect(() => {
    router.replace('/labeling/owner');
  }, [router]);
  return (
    <main className="mx-auto max-w-3xl px-4 py-8 text-sm text-zinc-500">
      운영 현황으로 이동 중…
    </main>
  );
}

export default function HomeSwitch() {
  const { access } = useLabelingAccess();
  if (access?.status === 'labeler') return <BlindReviewQueue />;
  if (access?.status === 'owner') return <OwnerHomeRedirect />;
  return null;
}
