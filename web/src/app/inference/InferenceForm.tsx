'use client';
import { useMemo, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';

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

  function selectAll() {
    setSelected(new Set(clips.map((c) => c.id)));
  }
  function selectNone() {
    setSelected(new Set());
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
    <main className="mx-auto max-w-3xl p-8 space-y-4">
      <div className="flex items-baseline justify-between">
        <h1 className="text-2xl font-bold">F3 — Gemini 추론</h1>
        <Link href="/results" className="text-sm text-blue-600 hover:underline">
          결과 보기 →
        </Link>
      </div>

      <p className="text-sm text-gray-600">
        대기 {clips.length}건 · 선택 {selected.size}건 ({(totalSize / 1024 / 1024).toFixed(1)}MB)
      </p>

      <div className="flex gap-2 text-sm">
        <button onClick={selectAll} className="border rounded px-2 py-1">
          전체 선택
        </button>
        <button onClick={selectNone} className="border rounded px-2 py-1">
          해제
        </button>
        <button
          onClick={run}
          disabled={selected.size === 0 || running}
          className="bg-blue-600 text-white rounded px-4 py-1 ml-auto disabled:opacity-40"
        >
          {running ? `추론 중... (${selected.size}건)` : `선택 일괄 추론 (${selected.size})`}
        </button>
      </div>

      <ul className="divide-y border rounded">
        {clips.map((c) => (
          <li key={c.id} className="flex items-center gap-3 p-2 text-sm">
            <input
              type="checkbox"
              checked={selected.has(c.id)}
              onChange={() => toggle(c.id)}
            />
            <span className="font-mono text-xs w-20">{c.id.slice(0, 8)}</span>
            <span className="flex-1">{new Date(c.started_at).toLocaleString('ko-KR')}</span>
            <span className="text-gray-500">
              {c.source} · {c.duration_sec.toFixed(1)}s
            </span>
          </li>
        ))}
      </ul>

      {results.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-lg font-semibold">
            결과 — 성공 {okCount} / 실패 {failCount}
          </h2>
          <ul className="divide-y border rounded text-sm">
            {results.map((r, i) => (
              <li key={`${r.clip_id}-${i}`} className="p-2 flex gap-3">
                <span className="font-mono text-xs w-20">{r.clip_id.slice(0, 8)}</span>
                {r.ok ? (
                  <>
                    <span className="text-green-700">✓ {r.action}</span>
                    <span className="text-gray-500">
                      conf {r.confidence?.toFixed(2)}
                    </span>
                  </>
                ) : (
                  <span className="text-red-600">✗ {r.error}</span>
                )}
              </li>
            ))}
          </ul>
          <button
            onClick={() => router.refresh()}
            className="text-sm text-blue-600 hover:underline"
          >
            큐 갱신
          </button>
        </section>
      )}
    </main>
  );
}
