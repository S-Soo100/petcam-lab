'use client';

// PoC 대시보드 — 로그인 + DEV_USER_ID 본인만 접근.
//
// 흐름:
// - 비로그인 → /labeling/login
// - owner (DEV_USER_ID) → 대시보드 렌더
// - 그 외 (라벨러 / PoC env 없는 라벨링 도메인) → /labeling 으로 redirect
//
// stats 조회는 /api/poc/summary route handler 가 service_role 로 처리.
// 라우트가 401/403/404 응답하면 위 흐름대로 redirect.

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';

import { getSupabaseBrowser } from '@/lib/supabaseBrowser';
import { Page, PageHeader } from '@/components/ui/Page';
import Badge from '@/components/ui/Badge';

interface Stats {
  pool: number;
  labeled: number;
  inferred: number;
  paired: number;
}

export default function Home() {
  const router = useRouter();
  const [stats, setStats] = useState<Stats | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const sb = getSupabaseBrowser();
      const {
        data: { session },
      } = await sb.auth.getSession();
      if (cancelled) return;
      if (!session) {
        router.replace('/labeling/login');
        return;
      }

      let resp: Response;
      try {
        resp = await fetch('/api/poc/summary', {
          headers: { Authorization: `Bearer ${session.access_token}` },
          cache: 'no-store',
        });
      } catch (e) {
        if (!cancelled) setErr((e as Error).message);
        return;
      }
      if (cancelled) return;

      if (resp.status === 401) {
        router.replace('/labeling/login');
        return;
      }
      if (resp.status === 403 || resp.status === 404) {
        router.replace('/labeling');
        return;
      }
      if (!resp.ok) {
        setErr(`HTTP ${resp.status}`);
        return;
      }
      const data: Stats = await resp.json();
      if (!cancelled) setStats(data);
    })();
    return () => {
      cancelled = true;
    };
  }, [router]);

  if (err) {
    return (
      <Page max="4xl">
        <div className="rounded-md bg-red-50 px-4 py-3 text-sm text-red-700 ring-1 ring-inset ring-red-200">
          {err}
        </div>
      </Page>
    );
  }

  if (!stats) {
    return (
      <Page max="4xl">
        <div className="text-sm text-zinc-500">불러오는 중…</div>
      </Page>
    );
  }

  const labelPending = Math.max(0, stats.pool - stats.labeled);
  const inferPending = Math.max(0, stats.labeled - stats.paired);

  return (
    <Page max="4xl">
      <PageHeader
        title="Round 1 대시보드"
        subtitle="Gemini 2.5 Flash × 크레스티드 게코 8 행동 분류"
        right={<Badge tone="info">specs/feature-poc-vlm-web.md</Badge>}
      />

      <section className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="풀" value={stats.pool} hint="cam2 motion + 업로드" />
        <Stat label="GT 라벨" value={stats.labeled} hint={labelPending > 0 ? `대기 ${labelPending}` : '완료'} />
        <Stat label="VLM 추론" value={stats.inferred} hint={inferPending > 0 ? `대기 ${inferPending}` : '완료'} />
        <Stat label="평가 가능" value={stats.paired} hint="GT ∩ VLM" tone="primary" />
      </section>

      <section className="grid gap-3 sm:grid-cols-2">
        <NavCard
          href="/upload"
          tag="F1"
          title="영상 업로드"
          desc="mp4 + 종 → 라벨 큐로 진입"
        />
        <NavCard
          href="/queue"
          tag="F2"
          title="GT 라벨링"
          desc={labelPending > 0 ? `대기 ${labelPending}건` : '모두 라벨 완료'}
          highlight={labelPending > 0}
        />
        <NavCard
          href="/inference"
          tag="F3"
          title="Gemini 추론"
          desc={inferPending > 0 ? `추론 대기 ${inferPending}건` : '모두 추론 완료'}
          highlight={inferPending > 0 && labelPending === 0}
        />
        <NavCard
          href="/results"
          tag="·"
          title="결과 / 평가"
          desc={stats.paired > 0 ? `평가 가능 ${stats.paired}건` : 'GT × VLM 짝 없음'}
          highlight={stats.paired > 0 && inferPending === 0}
        />
      </section>
    </Page>
  );
}

function Stat({
  label,
  value,
  hint,
  tone = 'neutral',
}: {
  label: string;
  value: number;
  hint?: string;
  tone?: 'neutral' | 'primary';
}) {
  const accent =
    tone === 'primary'
      ? 'bg-blue-50/60 ring-blue-100'
      : 'bg-white ring-zinc-200';
  return (
    <div className={`rounded-xl px-4 py-3 ring-1 ${accent}`}>
      <div className="text-xs font-medium uppercase tracking-wide text-zinc-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums text-zinc-900">{value}</div>
      {hint && <div className="mt-0.5 text-xs text-zinc-500">{hint}</div>}
    </div>
  );
}

function NavCard({
  href,
  tag,
  title,
  desc,
  highlight = false,
}: {
  href: string;
  tag: string;
  title: string;
  desc: string;
  highlight?: boolean;
}) {
  return (
    <Link
      href={href}
      className={`group flex items-start gap-3 rounded-xl border p-4 transition-all hover:border-zinc-300 hover:shadow-sm ${
        highlight ? 'border-blue-200 bg-blue-50/40' : 'border-zinc-200 bg-white'
      }`}
    >
      <span
        className={`grid h-8 w-8 shrink-0 place-items-center rounded-md text-xs font-semibold ${
          highlight
            ? 'bg-blue-600 text-white'
            : 'bg-zinc-100 text-zinc-600 group-hover:bg-zinc-900 group-hover:text-white'
        }`}
      >
        {tag}
      </span>
      <div className="flex-1">
        <div className="font-medium text-zinc-900">{title}</div>
        <div className="text-sm text-zinc-500">{desc}</div>
      </div>
      <span className="text-zinc-300 transition-colors group-hover:text-zinc-500">→</span>
    </Link>
  );
}
