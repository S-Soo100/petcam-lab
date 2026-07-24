'use client';

// /labeling/owner — Owner 운영 현황 홈(설계 §7.1). 그룹별 제출률·미완료·불일치·Canary 현황을
// 한눈에 본다. '직접 라벨링'은 보조 버튼(/labeling/motion), 연구·진단 화면은 접힌 '연구 도구'로만
// 진입한다 — 상시 핵심 메뉴로 노출하지 않는다. 개별 제출 body 는 렌더하지 않는다(집계만).

import { useEffect, useState } from 'react';
import { Card } from '@/components/ui/Card';
import { ApiError } from '@/lib/labelingApi';
import { getOwnerOverview } from '@/lib/motionBlindReviewApi';
import type { OwnerOverview } from '@/lib/labelingRoleData';
import { DirectLabelingButton, OwnerOverviewView } from './_owner-overview-view';

export default function OwnerHomePage() {
  const [overview, setOverview] = useState<OwnerOverview | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = await getOwnerOverview();
        if (alive) setOverview(res);
      } catch (e) {
        if (alive) setErr(e instanceof ApiError ? e.message : (e as Error).message);
      } finally {
        if (alive) setBusy(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  if (busy) return <main className="min-w-0 px-4 py-6 text-sm text-zinc-500">불러오는 중…</main>;
  if (err || !overview) {
    return (
      <main className="min-w-0 space-y-3 px-4 py-6">
        <Card className="border-rose-200 bg-rose-50 text-sm text-rose-800">
          {err ?? '운영 현황을 불러오지 못했어.'}
        </Card>
        <DirectLabelingButton />
      </main>
    );
  }
  return <OwnerOverviewView overview={overview} />;
}
