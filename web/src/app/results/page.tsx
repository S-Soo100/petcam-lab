import Link from 'next/link';
import { supabaseAdmin } from '@/lib/supabase';
import { BEHAVIOR_CLASSES } from '@/types';

export const dynamic = 'force-dynamic';

interface Pair {
  clip_id: string;
  started_at: string;
  gt: string;
  vlm: string;
  vlm_conf: number | null;
  vlm_reasoning: string | null;
  match: boolean;
}

export default async function ResultsPage() {
  const [{ data: humanRows }, { data: vlmRows }] = await Promise.all([
    supabaseAdmin.from('behavior_logs').select('clip_id, action').eq('source', 'human'),
    supabaseAdmin
      .from('behavior_logs')
      .select('clip_id, action, confidence, reasoning')
      .eq('source', 'vlm'),
  ]);

  // 같은 clip에 GT 여러 개 있을 수 있음 → 가장 최근 1개. 여기선 단순 last-wins.
  const humanMap = new Map<string, string>();
  for (const r of humanRows ?? []) humanMap.set(r.clip_id as string, r.action as string);

  const pairs: Pair[] = [];
  for (const v of vlmRows ?? []) {
    const gt = humanMap.get(v.clip_id as string);
    if (!gt) continue;
    pairs.push({
      clip_id: v.clip_id as string,
      started_at: '',
      gt,
      vlm: v.action as string,
      vlm_conf: (v.confidence as number | null) ?? null,
      vlm_reasoning: (v.reasoning as string | null) ?? null,
      match: gt === v.action,
    });
  }

  if (pairs.length > 0) {
    const { data: clips } = await supabaseAdmin
      .from('camera_clips')
      .select('id, started_at')
      .in('id', pairs.map((p) => p.clip_id));
    const tsMap = new Map((clips ?? []).map((c) => [c.id as string, c.started_at as string]));
    for (const p of pairs) p.started_at = tsMap.get(p.clip_id) ?? '';
    pairs.sort((a, b) => b.started_at.localeCompare(a.started_at));
  }

  const total = pairs.length;
  const matchCount = pairs.filter((p) => p.match).length;
  const top1 = total > 0 ? matchCount / total : 0;

  // Confusion matrix: gt × vlm. 8 클래스 행/열로 고정 표시 (스펙 §3-6 "8×8")
  const labels = [...BEHAVIOR_CLASSES] as string[];
  const cm: Record<string, Record<string, number>> = {};
  for (const gt of labels) {
    cm[gt] = {};
    for (const pr of labels) cm[gt][pr] = 0;
  }
  for (const p of pairs) {
    if (cm[p.gt] && cm[p.gt][p.vlm] !== undefined) cm[p.gt][p.vlm]++;
  }
  const rowSums = Object.fromEntries(
    labels.map((l) => [l, labels.reduce((s, c) => s + cm[l][c], 0)]),
  );

  // Confidence buckets (10% 단위) × correct/wrong
  const buckets = new Map<string, { correct: number; wrong: number }>();
  for (const p of pairs) {
    if (p.vlm_conf === null) continue;
    const b = (Math.floor(p.vlm_conf * 10) / 10).toFixed(1);
    if (!buckets.has(b)) buckets.set(b, { correct: 0, wrong: 0 });
    const slot = buckets.get(b)!;
    slot[p.match ? 'correct' : 'wrong']++;
  }
  const sortedBuckets = Array.from(buckets.entries()).sort((a, b) =>
    b[0].localeCompare(a[0]),
  );

  return (
    <main className="mx-auto max-w-5xl p-8 space-y-8">
      <div className="flex items-baseline justify-between">
        <h1 className="text-2xl font-bold">Round 1 결과</h1>
        <Link href="/inference" className="text-sm text-blue-600 hover:underline">
          ← 추론
        </Link>
      </div>

      <section className="space-y-2">
        <div className="text-3xl font-bold">
          Top-1: {(top1 * 100).toFixed(1)}%{' '}
          <span className="text-base text-gray-500 font-normal">
            ({matchCount}/{total})
          </span>
        </div>
        <p className="text-sm text-gray-600">
          {top1 >= 0.7
            ? '✅ 70% 달성 → Phase 1 진입 검토'
            : top1 >= 0.5
              ? '🟡 50~70% → 프롬프트 튜닝 / few-shot'
              : '🔴 <50% → 전략 재검토 (스펙 §0-16)'}
        </p>
      </section>

      <section className="space-y-2">
        <h2 className="text-lg font-semibold">Pair 목록</h2>
        {pairs.length === 0 ? (
          <p className="text-gray-500 text-sm">
            GT+VLM 짝 없음. <Link href="/queue" className="text-blue-600">/queue</Link> →{' '}
            <Link href="/inference" className="text-blue-600">/inference</Link> 순서 진행.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="text-sm w-full border">
              <thead className="bg-gray-50">
                <tr>
                  <th className="text-left p-2">시각</th>
                  <th className="text-left p-2">Clip</th>
                  <th className="text-left p-2">GT</th>
                  <th className="text-left p-2">VLM</th>
                  <th className="text-left p-2">Conf</th>
                  <th className="text-left p-2">Reasoning</th>
                  <th className="text-left p-2">동영상</th>
                </tr>
              </thead>
              <tbody>
                {pairs.map((p) => (
                  <tr
                    key={p.clip_id}
                    className={p.match ? 'bg-green-50' : 'bg-red-50'}
                  >
                    <td className="p-2 whitespace-nowrap">
                      {p.started_at && new Date(p.started_at).toLocaleString('ko-KR')}
                    </td>
                    <td className="p-2 font-mono text-xs">{p.clip_id.slice(0, 8)}</td>
                    <td className="p-2">{p.gt}</td>
                    <td className="p-2">
                      {p.match ? '✅' : '❌'} {p.vlm}
                    </td>
                    <td className="p-2">{p.vlm_conf?.toFixed(2) ?? '-'}</td>
                    <td className="p-2 text-xs text-gray-600 max-w-md">
                      {p.vlm_reasoning}
                    </td>
                    <td className="p-2">
                      <Link
                        href={`/clips/${p.clip_id}/label`}
                        className="text-blue-600 hover:underline text-xs"
                      >
                        보기
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="space-y-2">
        <h2 className="text-lg font-semibold">Confusion Matrix (행=GT, 열=VLM)</h2>
        <div className="overflow-x-auto">
          <table className="text-xs border">
            <thead className="bg-gray-50">
              <tr>
                <th className="p-1 border">GT \\ VLM</th>
                {labels.map((l) => (
                  <th key={l} className="p-1 border">
                    {l}
                  </th>
                ))}
                <th className="p-1 border bg-gray-100">합</th>
              </tr>
            </thead>
            <tbody>
              {labels.map((gt) => (
                <tr key={gt}>
                  <th className="p-1 border bg-gray-50 text-left">{gt}</th>
                  {labels.map((pr) => {
                    const v = cm[gt][pr];
                    const isDiag = gt === pr;
                    return (
                      <td
                        key={pr}
                        className={`p-1 border text-center ${
                          v === 0 ? 'text-gray-300' : isDiag ? 'bg-green-100 font-bold' : 'bg-red-50'
                        }`}
                      >
                        {v || ''}
                      </td>
                    );
                  })}
                  <td className="p-1 border text-center bg-gray-50">{rowSums[gt]}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="space-y-2">
        <h2 className="text-lg font-semibold">Confidence 분포</h2>
        {sortedBuckets.length === 0 ? (
          <p className="text-gray-500 text-sm">데이터 없음</p>
        ) : (
          <table className="text-sm border">
            <thead className="bg-gray-50">
              <tr>
                <th className="p-2 border">Bucket</th>
                <th className="p-2 border text-green-700">Correct</th>
                <th className="p-2 border text-red-700">Wrong</th>
                <th className="p-2 border">정확률</th>
              </tr>
            </thead>
            <tbody>
              {sortedBuckets.map(([b, v]) => {
                const sum = v.correct + v.wrong;
                return (
                  <tr key={b}>
                    <td className="p-2 border font-mono">{b}</td>
                    <td className="p-2 border text-center">{v.correct}</td>
                    <td className="p-2 border text-center">{v.wrong}</td>
                    <td className="p-2 border text-center">
                      {sum > 0 ? `${((v.correct / sum) * 100).toFixed(0)}%` : '-'}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>
    </main>
  );
}
