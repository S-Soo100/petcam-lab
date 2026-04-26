import Link from 'next/link';
import { supabaseAdmin } from '@/lib/supabase';

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
  return (
    <main className="mx-auto max-w-2xl p-8 space-y-6">
      <h1 className="text-3xl font-bold">PoC VLM 라벨링 대시보드</h1>
      <p className="text-sm text-gray-600">
        Round 1 — Gemini 2.5 Flash × 크레스티드 게코 8 행동 분류 (specs/feature-poc-vlm-web.md)
      </p>

      <section className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-center">
        <Stat label="풀" value={s.pool} hint="cam2 + 업로드" />
        <Stat label="GT 라벨" value={s.labeled} />
        <Stat label="VLM 추론" value={s.inferred} />
        <Stat label="평가 가능" value={s.paired} hint="GT∩VLM" />
      </section>

      <nav className="grid sm:grid-cols-2 gap-3">
        <NavCard href="/upload" title="F1 업로드" desc="영상 + 종 → 라벨 큐로" />
        <NavCard
          href="/queue"
          title="F2 라벨 큐"
          desc={`대기 ${Math.max(0, s.pool - s.labeled)}건`}
        />
        <NavCard
          href="/inference"
          title="F3 Gemini 추론"
          desc={`대기 ${Math.max(0, s.labeled - s.paired)}건`}
        />
        <NavCard href="/results" title="결과" desc={`평가 ${s.paired}건`} />
      </nav>
    </main>
  );
}

function Stat({ label, value, hint }: { label: string; value: number; hint?: string }) {
  return (
    <div className="border rounded p-3">
      <div className="text-2xl font-bold">{value}</div>
      <div className="text-xs text-gray-600">{label}</div>
      {hint && <div className="text-[10px] text-gray-400">{hint}</div>}
    </div>
  );
}

function NavCard({ href, title, desc }: { href: string; title: string; desc: string }) {
  return (
    <Link href={href} className="border rounded p-4 hover:bg-gray-50 transition-colors">
      <div className="font-semibold">{title}</div>
      <div className="text-sm text-gray-600">{desc}</div>
    </Link>
  );
}
