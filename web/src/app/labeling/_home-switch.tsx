'use client';

// /labeling 홈 스위치(설계 §3.2·§4, v4 갱신). 두 역할 모두 기본 홈이 별도 경로라 여기서 명시적으로
// 이동한다 — 승인 라벨러는 내 카메라(/labeling/mine, v4 스펙 §2 In 3), Owner 는 운영 현황
// (/labeling/owner). 라벨링은 목록 카드에서 상세로 진입한다. pending/rejected 는 layout 가드가
// 이미 대기 화면으로 라우팅하므로 여기서는 null.

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';

import { useLabelingAccess } from './_owner-context';

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

function LabelerHomeRedirect() {
  const router = useRouter();
  useEffect(() => {
    router.replace('/labeling/mine');
  }, [router]);
  return (
    <main className="mx-auto max-w-3xl px-4 py-8 text-sm text-zinc-500">
      내 카메라로 이동 중…
    </main>
  );
}

export default function HomeSwitch() {
  const { access } = useLabelingAccess();
  if (access?.status === 'labeler') return <LabelerHomeRedirect />;
  if (access?.status === 'owner') return <OwnerHomeRedirect />;
  return null;
}
