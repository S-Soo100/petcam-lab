'use client';

import { useEffect, useState } from 'react';

import { Card } from '@/components/ui/Card';
import Button from '@/components/ui/Button';
import {
  BLIND_ONBOARDING_REOPEN,
  BLIND_ONBOARDING_SENTENCES,
  BLIND_ONBOARDING_START,
  blindOnboardingKey,
} from './_blind-review-view';

// 첫 접속 1분 안내(설계 §4.1·§9). 세 문장 + '작업 시작' + 항상 다시 열 수 있는 '작업 방법'.
// 닫았다는 상태만 localStorage 에 사용자별로 저장한다. 저장 실패는 큐를 막지 않는다.
export default function BlindReviewOnboarding({ userId }: { userId: string | null }) {
  const [dismissed, setDismissed] = useState(true); // SSR 안전: 마운트 전에는 배너를 그리지 않는다.
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!userId) return;
    try {
      setDismissed(localStorage.getItem(blindOnboardingKey(userId)) === 'dismissed');
    } catch {
      setDismissed(false); // 저장소 접근 불가 = 안내를 보여준다(막지 않는다).
    }
  }, [userId]);

  const showBanner = open || !dismissed;

  function dismiss() {
    setOpen(false);
    setDismissed(true);
    if (!userId) return;
    try {
      localStorage.setItem(blindOnboardingKey(userId), 'dismissed');
    } catch {
      /* 저장 실패는 무시 — 큐는 그대로 쓴다. */
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex justify-end">
        <Button variant="labelingSecondary" size="sm" onClick={() => setOpen(true)}>
          {BLIND_ONBOARDING_REOPEN}
        </Button>
      </div>
      {showBanner && (
        <Card className="space-y-3 border-emerald-200 bg-emerald-50">
          <ul className="space-y-1.5 text-sm text-emerald-950">
            {BLIND_ONBOARDING_SENTENCES.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
          <Button variant="labelingPrimary" size="md" onClick={dismiss}>
            {BLIND_ONBOARDING_START}
          </Button>
        </Card>
      )}
    </div>
  );
}
