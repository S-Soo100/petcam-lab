'use client';

// canary 동일 링크(설계 §8). 같은 URL 을 로그인 역할에 따라 다르게 렌더한다:
// - 라벨러: 자기에게 배정된 canary 작업 카드 + 본인 진행. 상대 답안·상대 상태 비공개.
// - Owner:  cohort 현황(전체/제출/상태 집계) + 두 라벨러 완료 수 + 공유 링크 복사 + 불일치 검수 진입.
// live 큐·활동일 progress 는 절대 건드리지 않는다. 닫힘/미존재 cohort 는 라벨러에게 만료로 접힌다.

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';

import { Card } from '@/components/ui/Card';
import { ApiError } from '@/lib/labelingApi';
import { getBlindCanary, type BlindCanaryResponse } from '@/lib/motionBlindReviewApi';
import { CanaryLabelerView, CanaryOwnerView } from './_canary-views';

export default function BlindCanaryEntryPage() {
  const { cohortId } = useParams<{ cohortId: string }>();
  const [data, setData] = useState<BlindCanaryResponse | null>(null);
  const [expired, setExpired] = useState(false);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      setBusy(true);
      try {
        const res = await getBlindCanary(cohortId);
        if (alive) setData(res);
      } catch (e) {
        if (!alive) return;
        if (e instanceof ApiError && (e.code === 'cohort_closed' || e.status === 410 || e.status === 404)) {
          setExpired(true);
        } else {
          setError(e instanceof ApiError ? e.message : (e as Error).message);
        }
      } finally {
        if (alive) setBusy(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [cohortId]);

  if (busy) return <main className="mx-auto max-w-3xl px-4 py-6 text-sm text-zinc-500">불러오는 중…</main>;

  if (expired) {
    return (
      <main className="mx-auto max-w-3xl space-y-3 px-4 py-6">
        <Card className="border-amber-200 bg-amber-50 text-sm text-amber-900">
          검증 링크가 만료됐어. 관리자에게 문의해.
        </Card>
        <Link className="text-sm text-emerald-700 underline" href="/labeling">홈으로 돌아가기</Link>
      </main>
    );
  }

  if (error) {
    return (
      <main className="mx-auto max-w-3xl px-4 py-6">
        <Card className="border-rose-200 bg-rose-50 text-sm text-rose-800">{error}</Card>
      </main>
    );
  }

  if (!data) return null;
  return data.role === 'owner' ? (
    <CanaryOwnerView data={data} />
  ) : (
    <CanaryLabelerView data={data} cohortId={cohortId} />
  );
}
