import Link from 'next/link';
import { supabaseAdmin } from '@/lib/supabase';
import { Card } from '@/components/ui/Card';
import { Page, PageHeader } from '@/components/ui/Page';
import Badge from '@/components/ui/Badge';

export const dynamic = 'force-dynamic';

const DEV_USER_ID = process.env.DEV_USER_ID!;
const ROUND1_CAMERA_ID = process.env.ROUND1_CAMERA_ID!;

async function summary() {
  const [{ count: poolCount }, { data: gtRows }, { data: vlmRows }] = await Promise.all([
    supabaseAdmin
      .from('camera_clips')
      .select('id', { count: 'exact', head: true })
      .eq('user_id', DEV_USER_ID)
      .or(`source.eq.upload,camera_id.eq.${ROUND1_CAMERA_ID}`)
      .eq('has_motion', true),
    supabaseAdmin.from('behavior_logs').select('clip_id').eq('source', 'human'),
    supabaseAdmin.from('behavior_logs').select('clip_id').eq('source', 'vlm'),
  ]);
  const gtIds = new Set((gtRows ?? []).map((r) => r.clip_id as string));
  const vlmIds = new Set((vlmRows ?? []).map((r) => r.clip_id as string));
  return {
    pool: poolCount ?? 0,
    labeled: gtIds.size,
    inferred: vlmIds.size,
    paired: Array.from(vlmIds).filter((id) => gtIds.has(id)).length,
  };
}

export default async function Home() {
  const s = await summary();
  const labelPending = Math.max(0, s.pool - s.labeled);
  const inferPending = Math.max(0, s.labeled - s.paired);

  return (
    <Page max="4xl">
      <PageHeader
        title="Round 1 대시보드"
        subtitle="Gemini 2.5 Flash × 크레스티드 게코 8 행동 분류"
        right={<Badge tone="info">specs/feature-poc-vlm-web.md</Badge>}
      />

      <section className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="풀" value={s.pool} hint="cam2 motion + 업로드" />
        <Stat label="GT 라벨" value={s.labeled} hint={labelPending > 0 ? `대기 ${labelPending}` : '완료'} />
        <Stat label="VLM 추론" value={s.inferred} hint={inferPending > 0 ? `대기 ${inferPending}` : '완료'} />
        <Stat label="평가 가능" value={s.paired} hint="GT ∩ VLM" tone="primary" />
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
          desc={s.paired > 0 ? `평가 가능 ${s.paired}건` : 'GT × VLM 짝 없음'}
          highlight={s.paired > 0 && inferPending === 0}
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
