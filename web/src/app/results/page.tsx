import Link from 'next/link';
import { supabaseAdmin } from '@/lib/supabase';
import { BEHAVIOR_CLASSES } from '@/types';
import { Page, PageHeader } from '@/components/ui/Page';
import { Card, CardTitle } from '@/components/ui/Card';
import Badge from '@/components/ui/Badge';

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
    supabaseAdmin
      .from('behavior_logs')
      .select('clip_id, action, created_at')
      .eq('source', 'human')
      .order('created_at', { ascending: true }),
    supabaseAdmin
      .from('behavior_logs')
      .select('clip_id, action, confidence, reasoning, created_at')
      .eq('source', 'vlm')
      .order('created_at', { ascending: true }),
  ]);

  // last-wins per clip
  const humanMap = new Map<string, string>();
  for (const r of humanRows ?? []) humanMap.set(r.clip_id as string, r.action as string);
  const vlmMap = new Map<string, { action: string; conf: number | null; reasoning: string | null }>();
  for (const v of vlmRows ?? []) {
    vlmMap.set(v.clip_id as string, {
      action: v.action as string,
      conf: (v.confidence as number | null) ?? null,
      reasoning: (v.reasoning as string | null) ?? null,
    });
  }

  const pairs: Pair[] = [];
  Array.from(vlmMap.entries()).forEach(([clipId, vlm]) => {
    const gt = humanMap.get(clipId);
    if (!gt) return;
    pairs.push({
      clip_id: clipId,
      started_at: '',
      gt,
      vlm: vlm.action,
      vlm_conf: vlm.conf,
      vlm_reasoning: vlm.reasoning,
      match: gt === vlm.action,
    });
  });

  if (pairs.length > 0) {
    const { data: clips } = await supabaseAdmin
      .from('camera_clips')
      .select('id, started_at')
      .in(
        'id',
        pairs.map((p) => p.clip_id),
      );
    const tsMap = new Map((clips ?? []).map((c) => [c.id as string, c.started_at as string]));
    for (const p of pairs) p.started_at = tsMap.get(p.clip_id) ?? '';
    pairs.sort((a, b) => b.started_at.localeCompare(a.started_at));
  }

  const total = pairs.length;
  const matchCount = pairs.filter((p) => p.match).length;
  const top1 = total > 0 ? matchCount / total : 0;

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

  const buckets = new Map<string, { correct: number; wrong: number }>();
  for (const p of pairs) {
    if (p.vlm_conf === null) continue;
    const b = (Math.floor(p.vlm_conf * 10) / 10).toFixed(1);
    if (!buckets.has(b)) buckets.set(b, { correct: 0, wrong: 0 });
    const slot = buckets.get(b)!;
    slot[p.match ? 'correct' : 'wrong']++;
  }
  const sortedBuckets = Array.from(buckets.entries()).sort((a, b) => b[0].localeCompare(a[0]));

  const verdictTone: 'success' | 'warning' | 'danger' =
    top1 >= 0.7 ? 'success' : top1 >= 0.5 ? 'warning' : 'danger';
  const verdictText =
    top1 >= 0.7
      ? 'Phase 1 진입 검토 (≥70%)'
      : top1 >= 0.5
        ? '프롬프트 튜닝 / few-shot (50~70%)'
        : '전략 재검토 (<50%, §0-16)';

  return (
    <Page max="6xl">
      <PageHeader
        title="Round 1 결과"
        subtitle="GT vs VLM (Gemini 2.5 Flash) — last-wins per clip"
      />

      <Card padding="lg" className="bg-gradient-to-br from-white to-zinc-50">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <div className="text-xs font-medium uppercase tracking-wide text-zinc-500">
              Top-1 정확도
            </div>
            <div className="mt-1 flex items-baseline gap-3">
              <div className="text-5xl font-semibold tabular-nums text-zinc-900">
                {(top1 * 100).toFixed(1)}
                <span className="text-2xl font-normal text-zinc-400">%</span>
              </div>
              <div className="text-sm tabular-nums text-zinc-500">
                {matchCount} / {total}
              </div>
            </div>
          </div>
          <Badge tone={verdictTone}>{verdictText}</Badge>
        </div>
      </Card>

      <Card>
        <div className="mb-3 flex items-baseline justify-between">
          <CardTitle>Pair 목록</CardTitle>
          <span className="text-xs text-zinc-500">{pairs.length}건</span>
        </div>
        {pairs.length === 0 ? (
          <p className="py-6 text-center text-sm text-zinc-500">
            GT × VLM 짝 없음.{' '}
            <Link href="/queue" className="text-zinc-900 underline">
              /queue
            </Link>{' '}
            →{' '}
            <Link href="/inference" className="text-zinc-900 underline">
              /inference
            </Link>{' '}
            진행.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-zinc-200 text-left text-xs font-medium uppercase tracking-wide text-zinc-500">
                  <th className="py-2 pr-3 font-medium">시각</th>
                  <th className="py-2 pr-3 font-medium">Clip</th>
                  <th className="py-2 pr-3 font-medium">GT</th>
                  <th className="py-2 pr-3 font-medium">VLM</th>
                  <th className="py-2 pr-3 font-medium">Conf</th>
                  <th className="py-2 pr-3 font-medium">Reasoning</th>
                  <th className="py-2 font-medium"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100">
                {pairs.map((p) => (
                  <tr key={p.clip_id} className="hover:bg-zinc-50">
                    <td className="py-2 pr-3 text-xs tabular-nums text-zinc-500 whitespace-nowrap">
                      {p.started_at &&
                        new Date(p.started_at).toLocaleString('ko-KR', {
                          timeZone: 'Asia/Seoul',
                          dateStyle: 'short',
                          timeStyle: 'short',
                        })}
                    </td>
                    <td className="py-2 pr-3 font-mono text-xs text-zinc-500">
                      {p.clip_id.slice(0, 8)}
                    </td>
                    <td className="py-2 pr-3">
                      <Badge tone="neutral">{p.gt}</Badge>
                    </td>
                    <td className="py-2 pr-3">
                      <Badge tone={p.match ? 'success' : 'danger'}>{p.vlm}</Badge>
                    </td>
                    <td className="py-2 pr-3 text-xs tabular-nums text-zinc-600">
                      {p.vlm_conf?.toFixed(2) ?? '-'}
                    </td>
                    <td className="py-2 pr-3 max-w-md text-xs text-zinc-600">
                      {p.vlm_reasoning}
                    </td>
                    <td className="py-2">
                      <Link
                        href={`/clips/${p.clip_id}/label`}
                        className="text-xs text-zinc-500 hover:text-zinc-900"
                      >
                        보기 →
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
        <Card>
          <div className="mb-3 flex items-baseline justify-between">
            <CardTitle>Confusion Matrix</CardTitle>
            <span className="text-xs text-zinc-500">행=GT · 열=VLM</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr>
                  <th className="px-2 py-1.5 text-left font-medium text-zinc-500"></th>
                  {labels.map((l) => (
                    <th
                      key={l}
                      className="px-1.5 py-1.5 text-center font-medium text-zinc-500"
                    >
                      <span className="inline-block max-w-[60px] truncate" title={l}>
                        {l}
                      </span>
                    </th>
                  ))}
                  <th className="px-2 py-1.5 text-center font-medium text-zinc-500">합</th>
                </tr>
              </thead>
              <tbody>
                {labels.map((gt) => (
                  <tr key={gt} className="border-t border-zinc-100">
                    <th className="px-2 py-1.5 text-left font-medium text-zinc-700">{gt}</th>
                    {labels.map((pr) => {
                      const v = cm[gt][pr];
                      const isDiag = gt === pr;
                      return (
                        <td
                          key={pr}
                          className={`px-1.5 py-1.5 text-center tabular-nums ${
                            v === 0
                              ? 'text-zinc-300'
                              : isDiag
                                ? 'bg-emerald-50 font-semibold text-emerald-700'
                                : 'bg-red-50 text-red-700'
                          }`}
                        >
                          {v || ''}
                        </td>
                      );
                    })}
                    <td className="px-2 py-1.5 text-center tabular-nums text-zinc-600">
                      {rowSums[gt]}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        <Card>
          <CardTitle className="mb-3">Confidence 분포</CardTitle>
          {sortedBuckets.length === 0 ? (
            <p className="text-sm text-zinc-500">데이터 없음</p>
          ) : (
            <div className="space-y-2">
              {sortedBuckets.map(([b, v]) => {
                const sum = v.correct + v.wrong;
                const pct = sum > 0 ? (v.correct / sum) * 100 : 0;
                return (
                  <div key={b} className="space-y-1">
                    <div className="flex items-baseline justify-between text-xs">
                      <span className="font-mono text-zinc-700">{b}+</span>
                      <span className="text-zinc-500 tabular-nums">
                        {v.correct}/{sum} · {pct.toFixed(0)}%
                      </span>
                    </div>
                    <div className="flex h-1.5 overflow-hidden rounded-full bg-zinc-100">
                      <div
                        className="bg-emerald-500"
                        style={{ width: `${sum > 0 ? (v.correct / sum) * 100 : 0}%` }}
                      />
                      <div
                        className="bg-red-400"
                        style={{ width: `${sum > 0 ? (v.wrong / sum) * 100 : 0}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </Card>
      </div>
    </Page>
  );
}
