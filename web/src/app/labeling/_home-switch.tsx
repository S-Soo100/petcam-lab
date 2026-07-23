'use client';

// /labeling 홈 스위치(설계 §4·계획 Task 5). 승인 라벨러는 이중 블라인드 활동일 큐를, owner 는
// 기존 운영 큐(env 로 고른 motion/legacy)를 본다. pending/rejected 는 layout 가드가 대기 화면으로
// 이미 라우팅하므로 여기서는 owner fallback 만 렌더한다.

import type { ReactNode } from 'react';

import { useIsLabeler } from './_owner-context';
import BlindReviewQueue from './_blind-review-queue';

export default function HomeSwitch({ ownerQueue }: { ownerQueue: ReactNode }) {
  const isLabeler = useIsLabeler();
  return isLabeler ? <BlindReviewQueue /> : <>{ownerQueue}</>;
}
