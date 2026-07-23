'use client';

// canary 진입점(설계 §6.3). owner 가 발급한 격리 링크에서만 자기 canary slot 을 본다. live 큐·
// 진행률·export 와 분리된다. 열린 canary 만 노출하고, 닫힘/미존재 cohort 는 안전한 만료 상태.
// 활동일 unlock/progress 는 절대 건드리지 않는다.

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';

import { Card, CardTitle } from '@/components/ui/Card';
import { ApiError } from '@/lib/labelingApi';
import { formatClipCapturedAt } from '@/lib/labelingV2';
import { getBlindCanary, type BlindCanaryResponse } from '@/lib/motionBlindReviewApi';

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
        <Link className="text-sm text-emerald-700 underline" href="/labeling">큐로 돌아가기</Link>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-3xl space-y-3 px-4 py-6">
      <div className="inline-flex w-fit rounded-full bg-sky-100 px-2.5 py-0.5 text-xs font-semibold text-sky-900">
        검증용 작업
      </div>
      {data && (
        <Card className="text-sm text-zinc-700">
          검증 진행 {data.submitted_count}/{data.total_count}
        </Card>
      )}
      {error && <Card className="border-rose-200 bg-rose-50 text-sm text-rose-800">{error}</Card>}

      {data && data.items.length === 0 ? (
        <Card className="text-sm text-zinc-700">검증 작업을 모두 끝냈어.</Card>
      ) : (
        <ul className="space-y-2">
          {data?.items.map((item) => (
            <li key={item.id}>
              <Link
                href={`/labeling/blind/canary/${cohortId}/${item.id}`}
                className="block rounded-xl border border-zinc-200 bg-white p-3 text-sm shadow-sm hover:border-zinc-400"
              >
                <div className="font-medium text-zinc-900">{item.camera_name}</div>
                <div className="text-xs text-zinc-500">
                  {formatClipCapturedAt(item.started_at, item.duration_sec)}
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
