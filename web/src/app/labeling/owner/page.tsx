'use client';

// /labeling/owner — Owner 운영 현황 홈(설계 §7.1). 그룹별 제출률·미완료·불일치·Canary 현황을
// 한눈에 본다. '직접 라벨링'은 보조 버튼(/labeling/motion), 연구·진단 화면은 접힌 '연구 도구'로만
// 진입한다 — 상시 핵심 메뉴로 노출하지 않는다. 개별 제출 body 는 렌더하지 않는다(집계만).

import { useEffect, useState } from 'react';
import Link from 'next/link';

import Badge from '@/components/ui/Badge';
import { Card } from '@/components/ui/Card';
import { ApiError } from '@/lib/labelingApi';
import { getOwnerOverview } from '@/lib/motionBlindReviewApi';
import type { OwnerOverview } from '@/lib/labelingRoleData';

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

function DirectLabelingButton() {
  return (
    <Link
      href="/labeling/motion?state=unreviewed"
      className="inline-flex w-fit whitespace-nowrap rounded-md border border-emerald-500 bg-emerald-50 px-3 py-2 text-sm font-semibold text-emerald-950 hover:bg-emerald-100"
    >
      직접 라벨링
    </Link>
  );
}

// 순수 현황판 뷰(SSR 테스트 대상). 집계만 — 개별 제출 body 는 없다.
export function OwnerOverviewView({ overview }: { overview: OwnerOverview }) {
  const totalConflict = overview.groups.reduce((n, g) => n + g.conflict_count, 0);
  const totalAwaiting = overview.groups.reduce((n, g) => n + g.awaiting_count, 0);

  return (
    <main className="min-w-0 space-y-4 px-4 py-6">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div className="min-w-0">
          <h1 className="whitespace-nowrap text-xl font-semibold tracking-tight text-zinc-900">
            운영 현황
          </h1>
          <p className="text-sm text-zinc-500">기준 활동일 {overview.activity_day ?? '-'}</p>
        </div>
        <DirectLabelingButton />
      </div>

      <div className="flex flex-wrap gap-2 text-sm">
        <Badge tone={totalConflict > 0 ? 'warning' : 'neutral'}>불일치 {totalConflict}</Badge>
        <Badge tone="info">비교 대기 {totalAwaiting}</Badge>
      </div>

      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-zinc-800">그룹별 제출률</h2>
        {overview.groups.length === 0 ? (
          <Card className="text-sm text-zinc-600">활성 그룹이 없어.</Card>
        ) : (
          <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {overview.groups.map((g) => (
              <li key={g.group_id} className="min-w-0">
                <Card className="space-y-2 text-sm">
                  <div className="flex items-center justify-between gap-2">
                    <span className="min-w-0 truncate font-medium text-zinc-900">{g.group_name}</span>
                    <span className="text-xs text-zinc-500">전체 {g.clip_total}</span>
                  </div>
                  <ul className="space-y-0.5">
                    {g.members.map((m, i) => (
                      <li key={i} className="flex items-center justify-between gap-2">
                        <span className="min-w-0 truncate text-zinc-700">{m.display_name}</span>
                        <span className="tabular-nums text-zinc-600">{m.submitted_count}건</span>
                      </li>
                    ))}
                  </ul>
                  <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-zinc-600">
                    <span>합의 {g.agreed_count}</span>
                    <span>불일치 {g.conflict_count}</span>
                    <span>비교 대기 {g.awaiting_count}</span>
                  </div>
                </Card>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-zinc-800">열린 Canary</h2>
        {overview.open_canaries.length === 0 ? (
          <Card className="text-sm text-zinc-600">열린 검증 링크가 없어.</Card>
        ) : (
          <ul className="space-y-2">
            {overview.open_canaries.map((c) => (
              <li key={c.cohort_id}>
                <Link
                  href={`/labeling/blind/canary/${c.cohort_id}`}
                  className="block rounded-xl border border-zinc-200 bg-white p-3 text-sm shadow-sm hover:border-zinc-400"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="min-w-0 truncate font-medium text-zinc-900">
                      {c.label ?? '검증 코호트'}
                    </span>
                    <span className="text-xs text-zinc-500">
                      제출 {c.submitted_total}/{c.clip_total}
                    </span>
                  </div>
                  <div className="mt-0.5 text-xs text-zinc-500">불일치 {c.conflict_count}</div>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>

      <details className="rounded-md border border-zinc-200 bg-white p-3 text-sm">
        <summary className="cursor-pointer font-medium text-zinc-700">연구 도구</summary>
        <p className="mt-2 text-xs text-zinc-500">
          격리함·라우터 리뷰·실험성 진단은 상시 메뉴가 아니라 여기에서만 진입해.
        </p>
        <Link
          href="/labeling/owner/research"
          className="mt-2 inline-flex text-sm text-emerald-700 hover:underline"
        >
          연구 도구 열기
        </Link>
      </details>
    </main>
  );
}
