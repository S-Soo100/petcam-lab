'use client';
import { useMemo, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Page, PageHeader } from '@/components/ui/Page';
import { Card } from '@/components/ui/Card';
import Badge from '@/components/ui/Badge';
import Button from '@/components/ui/Button';

interface Clip {
  id: string;
  started_at: string;
  duration_sec: number;
  source: string;
  file_size: number | null;
}

interface RunResult {
  clip_id: string;
  ok: boolean;
  action?: string;
  confidence?: number;
  error?: string;
}

export default function InferenceForm({ clips }: { clips: Clip[] }) {
  const router = useRouter();
  const [selected, setSelected] = useState<Set<string>>(new Set(clips.map((c) => c.id)));
  const [running, setRunning] = useState(false);
  const [results, setResults] = useState<RunResult[]>([]);

  const totalSize = useMemo(
    () => clips.filter((c) => selected.has(c.id)).reduce((s, c) => s + (c.file_size ?? 0), 0),
    [clips, selected],
  );

  function toggle(id: string) {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelected(next);
  }

  async function run() {
    if (selected.size === 0 || running) return;
    setRunning(true);
    setResults([]);
    try {
      const res = await fetch('/api/inference', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ clip_ids: Array.from(selected) }),
      });
      const json = (await res.json()) as { results?: RunResult[]; error?: string };
      if (!res.ok) {
        setResults([{ clip_id: '-', ok: false, error: json.error ?? `HTTP ${res.status}` }]);
      } else {
        setResults(json.results ?? []);
      }
    } finally {
      setRunning(false);
    }
  }

  const okCount = results.filter((r) => r.ok).length;
  const failCount = results.filter((r) => !r.ok).length;

  return (
    <Page max="3xl">
      <PageHeader
        title="F3 — Gemini 추론"
        subtitle={`대기 ${clips.length}건 · 선택 ${selected.size}건 · ${(totalSize / 1024 / 1024).toFixed(1)}MB`}
        right={
          <Link
            href="/results"
            className="text-sm text-zinc-500 hover:text-zinc-900"
          >
            결과 →
          </Link>
        }
      />

      <Card padding="sm">
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setSelected(new Set(clips.map((c) => c.id)))}
          >
            전체
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setSelected(new Set())}>
            해제
          </Button>
          <div className="ml-auto">
            <Button
              size="md"
              onClick={run}
              disabled={selected.size === 0 || running}
            >
              {running ? `추론 중 (${selected.size}건)...` : `일괄 추론 (${selected.size})`}
            </Button>
          </div>
        </div>
      </Card>

      <Card padding="none">
        <ul className="divide-y divide-zinc-100">
          {clips.map((c) => {
            const sel = selected.has(c.id);
            return (
              <li key={c.id}>
                <label className="flex cursor-pointer items-center gap-3 px-4 py-2.5 text-sm hover:bg-zinc-50">
                  <input
                    type="checkbox"
                    checked={sel}
                    onChange={() => toggle(c.id)}
                    className="h-4 w-4 rounded border-zinc-300 accent-zinc-900"
                  />
                  <span className="font-mono text-xs text-zinc-500">{c.id.slice(0, 8)}</span>
                  <span className="flex-1 text-zinc-700">
                    {new Date(c.started_at).toLocaleString('ko-KR')}
                  </span>
                  <Badge tone={c.source === 'upload' ? 'info' : 'neutral'}>{c.source}</Badge>
                  <span className="w-12 text-right text-xs tabular-nums text-zinc-500">
                    {c.duration_sec.toFixed(0)}s
                  </span>
                </label>
              </li>
            );
          })}
        </ul>
      </Card>

      {results.length > 0 && (
        <Card>
          <div className="mb-3 flex items-center justify-between">
            <div className="flex items-center gap-2 text-sm font-semibold text-zinc-900">
              결과
              <Badge tone="success">성공 {okCount}</Badge>
              {failCount > 0 && <Badge tone="danger">실패 {failCount}</Badge>}
            </div>
            <button
              onClick={() => router.refresh()}
              className="text-xs text-zinc-500 hover:text-zinc-900"
            >
              새로고침
            </button>
          </div>
          <ul className="divide-y divide-zinc-100 text-sm">
            {results.map((r, i) => (
              <li key={`${r.clip_id}-${i}`} className="flex items-center gap-3 py-2">
                <span className="font-mono text-xs text-zinc-500">
                  {r.clip_id.slice(0, 8)}
                </span>
                {r.ok ? (
                  <>
                    <Badge tone="success">{r.action}</Badge>
                    <span className="text-xs tabular-nums text-zinc-500">
                      conf {r.confidence?.toFixed(2)}
                    </span>
                  </>
                ) : (
                  <span className="text-red-600">{r.error}</span>
                )}
              </li>
            ))}
          </ul>
        </Card>
      )}
    </Page>
  );
}
