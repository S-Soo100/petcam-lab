'use client';

import Link from 'next/link';

import Badge from '@/components/ui/Badge';
import { Card, CardTitle } from '@/components/ui/Card';
import type { V4Overview } from '@/lib/labelingV4';

export function DirectLabelingButton() {
  return (
    <Link
      href="/labeling/motion?state=unreviewed"
      className="inline-flex w-fit whitespace-nowrap rounded-md border border-emerald-500 bg-emerald-50 px-3 py-2 text-sm font-semibold text-emerald-950 hover:bg-emerald-100"
    >
      직접 라벨링(행동)
    </Link>
  );
}

// v4 운영 현황(순수 뷰, SSR 테스트 대상) — 집계만. 개별 확정 body·UUID 없음.
export function OwnerOverviewView({ overview }: { overview: V4Overview }) {
  return (
    <main className="min-w-0 space-y-4 px-4 py-6">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div className="min-w-0">
          <h1 className="whitespace-nowrap text-xl font-semibold tracking-tight text-zinc-900">운영 현황</h1>
          <p className="text-sm text-zinc-500">기준 활동일 {overview.activity_day ?? '-'}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link
            href="/labeling/all?label_state=unlabeled"
            className="inline-flex items-center rounded-md border border-zinc-300 px-3 py-2 text-sm text-zinc-800 hover:bg-zinc-50"
          >
            하이라이트 확정하기
          </Link>
          <DirectLabelingButton />
        </div>
      </div>
      <div className="flex flex-wrap gap-2 text-sm">
        <Badge tone="warning">라벨 안 된 영상 {overview.unlabeled_total}</Badge>
        <Badge tone="success">오늘 확정 {overview.labeled_today}</Badge>
        <Badge tone="neutral">7일 확정 {overview.labeled_7d}</Badge>
      </div>
      <Card className="space-y-2">
        <CardTitle>회원별 7일 확정</CardTitle>
        {overview.members.length === 0 ? (
          <p className="text-sm text-zinc-500">최근 7일 확정한 회원이 없어.</p>
        ) : (
          <ul className="text-sm">
            {overview.members.map((m) => (
              <li key={m.display_name}>
                {m.display_name} · {m.labeled_7d}
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Card className="space-y-2">
        <CardTitle>카메라별</CardTitle>
        {overview.cameras.length === 0 ? (
          <p className="text-sm text-zinc-500">카메라가 없어.</p>
        ) : (
          <ul className="text-sm">
            {overview.cameras.map((c) => (
              <li key={c.camera_name}>
                {c.camera_name} · 안 됨 {c.unlabeled} · 7일 확정 {c.labeled_7d}
              </li>
            ))}
          </ul>
        )}
      </Card>
      <p className="text-xs text-zinc-500">
        규칙 유지율은{' '}
        <Link href="/labeling/owner/highlight-rules" className="underline">
          하이라이트 규칙
        </Link>
        에서.
      </p>
    </main>
  );
}
