'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import Badge from '@/components/ui/Badge';
import { toFeedingMerged } from '@/types';

export interface Pair {
  clip_id: string;
  started_at: string;
  gt: string;
  gt_notes: string | null;
  vlm: string;
  vlm_conf: number | null;
  vlm_reasoning: string | null;
  match: boolean;
}

type Filter = 'all' | 'mismatch';
type Sort = 'time-desc' | 'conf-desc';

export default function PairTable({ pairs }: { pairs: Pair[] }) {
  const [filter, setFilter] = useState<Filter>('all');
  const [sort, setSort] = useState<Sort>('time-desc');
  const [hydrated, setHydrated] = useState(false);

  // URL → state (mount): /results?filter=mismatch&sort=conf-desc 로 진입해도 복원
  useEffect(() => {
    const sp = new URLSearchParams(window.location.search);
    if (sp.get('filter') === 'mismatch') setFilter('mismatch');
    if (sp.get('sort') === 'conf-desc') setSort('conf-desc');
    setHydrated(true);
  }, []);

  // state → URL (replace): router.push 안 씀 → 서버 재페치 없이 URL만 갱신
  useEffect(() => {
    if (!hydrated) return;
    const sp = new URLSearchParams(window.location.search);
    if (filter === 'all') sp.delete('filter');
    else sp.set('filter', filter);
    if (sort === 'time-desc') sp.delete('sort');
    else sp.set('sort', sort);
    const qs = sp.toString();
    const url = qs ? `${window.location.pathname}?${qs}` : window.location.pathname;
    window.history.replaceState(null, '', url);
  }, [filter, sort, hydrated]);

  const mismatchCount = pairs.filter((p) => !p.match).length;

  // GT note 패턴 기반 자동 카테고리 — 영상 재검토 우선순위 힌트
  const tagOf = (p: Pair): string | null => {
    const n = p.gt_notes ?? '';
    if (!p.match && (p.vlm_conf ?? 0) >= 0.95) return 'A';
    if (/추정|처럼|듯|같음|모호|아마|\?/.test(n)) return 'B';
    if (/\d+\s*초/.test(n)) return 'C';
    if (n.includes('auto-GT')) return 'D';
    return null;
  };

  const filtered = useMemo(() => {
    let arr = pairs;
    if (filter === 'mismatch') arr = arr.filter((p) => !p.match);
    if (sort === 'conf-desc') {
      arr = [...arr].sort((a, b) => (b.vlm_conf ?? 0) - (a.vlm_conf ?? 0));
    }
    return arr;
  }, [pairs, filter, sort]);

  // 영상 보고 돌아올 때 필터 유지: /clips/.../label?from=<현재 results URL>
  const buildLabelHref = (clipId: string) => {
    const sp = new URLSearchParams();
    if (filter !== 'all') sp.set('filter', filter);
    if (sort !== 'time-desc') sp.set('sort', sort);
    const ret = sp.toString() ? `/results?${sp.toString()}` : '/results';
    return `/clips/${clipId}/label?from=${encodeURIComponent(ret)}`;
  };

  const btn = (active: boolean, tone: 'neutral' | 'danger' = 'neutral') =>
    `rounded-md px-3 py-1 text-xs font-medium transition-colors ${
      active
        ? tone === 'danger'
          ? 'bg-red-600 text-white'
          : 'bg-zinc-900 text-white'
        : 'bg-zinc-100 text-zinc-700 hover:bg-zinc-200'
    }`;
  const sortBtn = (active: boolean) =>
    `rounded-md px-2 py-1 text-xs ${
      active ? 'bg-zinc-200 text-zinc-900' : 'text-zinc-500 hover:text-zinc-900'
    }`;

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <button onClick={() => setFilter('all')} className={btn(filter === 'all')}>
          전체 {pairs.length}
        </button>
        <button
          onClick={() => setFilter('mismatch')}
          className={btn(filter === 'mismatch', 'danger')}
        >
          Mismatch {mismatchCount}
        </button>
        <span className="ml-auto text-xs text-zinc-500">정렬</span>
        <button onClick={() => setSort('time-desc')} className={sortBtn(sort === 'time-desc')}>
          최신순
        </button>
        <button onClick={() => setSort('conf-desc')} className={sortBtn(sort === 'conf-desc')}>
          Conf↓ (GT 의심순)
        </button>
      </div>

      {filter === 'mismatch' && (
        <p className="mb-3 text-xs text-zinc-500">
          <span className="font-mono">A</span>=VLM자신만만(conf≥0.95) · <span className="font-mono">B</span>=GT모호표현 ·{' '}
          <span className="font-mono">C</span>=멀티행동(시점) · <span className="font-mono">D</span>=자동GT
        </p>
      )}

      {filtered.length === 0 ? (
        <p className="py-6 text-center text-sm text-zinc-500">해당 항목 없음</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-zinc-200 text-left text-xs font-medium uppercase tracking-wide text-zinc-500">
                <th className="py-2 pr-3 font-medium">시각</th>
                <th className="py-2 pr-3 font-medium">Clip</th>
                {filter === 'mismatch' && <th className="py-2 pr-3 font-medium">Tag</th>}
                <th className="py-2 pr-3 font-medium">GT</th>
                <th className="py-2 pr-3 font-medium">VLM</th>
                <th className="py-2 pr-3 font-medium">Conf</th>
                <th className="py-2 pr-3 font-medium">GT note</th>
                <th className="py-2 pr-3 font-medium">VLM Reasoning</th>
                <th className="py-2 font-medium"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-100">
              {filtered.map((p) => {
                const tag = tagOf(p);
                return (
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
                    {filter === 'mismatch' && (
                      <td className="py-2 pr-3 text-xs">
                        {tag && (
                          <span
                            className={`inline-block rounded px-1.5 py-0.5 font-mono font-semibold ${
                              tag === 'A'
                                ? 'bg-red-100 text-red-700'
                                : tag === 'B'
                                  ? 'bg-amber-100 text-amber-700'
                                  : tag === 'C'
                                    ? 'bg-amber-100 text-amber-700'
                                    : 'bg-emerald-100 text-emerald-700'
                            }`}
                          >
                            {tag}
                          </span>
                        )}
                      </td>
                    )}
                    <td className="py-2 pr-3">
                      {/* 표시는 매핑 후 (feeding-merged), title에 raw 라벨 보존 */}
                      <Badge tone="neutral" title={`raw: ${p.gt}`}>
                        {toFeedingMerged(p.gt)}
                      </Badge>
                    </td>
                    <td className="py-2 pr-3">
                      <Badge tone={p.match ? 'success' : 'danger'} title={`raw: ${p.vlm}`}>
                        {toFeedingMerged(p.vlm)}
                      </Badge>
                    </td>
                    <td className="py-2 pr-3 text-xs tabular-nums text-zinc-600">
                      {p.vlm_conf?.toFixed(2) ?? '-'}
                    </td>
                    <td className="py-2 pr-3 max-w-xs text-xs text-zinc-600">{p.gt_notes}</td>
                    <td className="py-2 pr-3 max-w-md text-xs text-zinc-600">
                      {p.vlm_reasoning}
                    </td>
                    <td className="py-2">
                      <Link
                        href={buildLabelHref(p.clip_id)}
                        className="text-xs text-zinc-500 hover:text-zinc-900"
                      >
                        보기 →
                      </Link>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
