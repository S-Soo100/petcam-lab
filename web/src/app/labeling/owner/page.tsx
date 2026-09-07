'use client';

// /labeling/owner — Owner 운영 현황 홈(v4 스펙 §2 In 5). 라벨 안 된 영상·오늘/7일 확정·회원별·카메라별
// 집계를 한눈에 본다. '직접 라벨링(행동)'은 보조 버튼(/labeling/motion). 개별 확정 body 는 렌더하지 않는다.

import { useEffect, useState } from 'react';
import { Card } from '@/components/ui/Card';
import { ApiError } from '@/lib/labelingApi';
import { getV4Overview } from '@/lib/labelingV4Api';
import type { V4Overview } from '@/lib/labelingV4';
import { DirectLabelingButton, OwnerOverviewView } from './_owner-overview-view';

export default function OwnerHomePage() {
  const [overview, setOverview] = useState<V4Overview | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = await getV4Overview();
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
