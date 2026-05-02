import Link from 'next/link';
import { supabaseAdmin } from '@/lib/supabase';
import { UI_BEHAVIOR_CLASSES, toFeedingMerged } from '@/types';
import { Page, PageHeader } from '@/components/ui/Page';
import { Card, CardTitle } from '@/components/ui/Card';
import Badge from '@/components/ui/Badge';
import PairTable, { type Pair } from './PairTable';

export const dynamic = 'force-dynamic';

export default async function ResultsPage() {
  const [{ data: humanRows }, { data: vlmRows }] = await Promise.all([
    supabaseAdmin
      .from('behavior_logs')
      .select('clip_id, action, notes, created_at')
      .eq('source', 'human')
      .order('created_at', { ascending: true }),
    supabaseAdmin
      .from('behavior_logs')
      .select('clip_id, action, confidence, reasoning, created_at')
      .eq('source', 'vlm')
      // v3.5 production lock-in baseline 한정 — 다른 라운드(v3.6/v3.7-B/v4) 결과는 archive로 보존되지만
      // 화면에는 노출 안 함. 잉여 라벨 노이즈 차단. (specs/feature-poc-vlm-web.md §3-14)
      .eq('vlm_model', 'gemini-2.5-flash-zeroshot-v3.5')
      .order('created_at', { ascending: true }),
  ]);

  // last-wins per clip
  const humanMap = new Map<string, { action: string; notes: string | null }>();
  for (const r of humanRows ?? [])
    humanMap.set(r.clip_id as string, {
      action: r.action as string,
      notes: (r.notes as string | null) ?? null,
    });
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
      gt: gt.action,
      gt_notes: gt.notes,
      vlm: vlm.action,
      vlm_conf: vlm.conf,
      vlm_reasoning: vlm.reasoning,
      // feeding-merged 매핑 후 일치 판정 (drinking + eating_paste → feeding).
      // 평가 레이어 매핑(web/eval/v35/analyze-v35-full.py FEEDING_MERGE)과 동치.
      match: toFeedingMerged(gt.action) === toFeedingMerged(vlm.action),
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

  // Confusion Matrix는 8클래스(UI_BEHAVIOR_CLASSES) 기준 — feeding-merged 노출.
  const labels = [...UI_BEHAVIOR_CLASSES] as string[];
  const cm: Record<string, Record<string, number>> = {};
  for (const gt of labels) {
    cm[gt] = {};
    for (const pr of labels) cm[gt][pr] = 0;
  }
  for (const p of pairs) {
    const gtMerged = toFeedingMerged(p.gt);
    const vlmMerged = toFeedingMerged(p.vlm);
    if (cm[gtMerged] && cm[gtMerged][vlmMerged] !== undefined) cm[gtMerged][vlmMerged]++;
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
          <PairTable pairs={pairs} />
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
