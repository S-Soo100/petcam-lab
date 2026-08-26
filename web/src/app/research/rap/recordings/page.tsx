'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';

import { getSupabaseBrowser } from '@/lib/supabaseBrowser';
import type { RapMode, RapRecordingSummary } from '@/lib/rapRecordings';
import { RecordingsView } from './_recordings-view';

type Coverage = { expected: number; captured: number; uploaded: number; failed: number; missing: number };

async function ownerFetch<T>(path: string): Promise<T> {
  const { data: { session } } = await getSupabaseBrowser().auth.getSession();
  const response = await fetch(path, { headers: session ? { Authorization: `Bearer ${session.access_token}` } : {} });
  if (!response.ok) throw new Error(response.status === 403 ? 'Owner만 볼 수 있어.' : '녹화 자료를 불러오지 못했어.');
  return response.json() as Promise<T>;
}

function todayKst(): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
}

export default function RapRecordingsPage() {
  const [mode, setMode] = useState<RapMode>('production');
  const [night, setNight] = useState(todayKst);
  const [camera, setCamera] = useState('');
  const [items, setItems] = useState<RapRecordingSummary[]>([]);
  const [coverage, setCoverage] = useState<Coverage | null>(null);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      const query = new URLSearchParams({ mode, limit: '100' });
      if (mode === 'production') query.set('night', night);
      if (camera) query.set('camera', camera);
      const data = await ownerFetch<{ items: RapRecordingSummary[]; coverage: Coverage | null }>(`/api/research/rap/recordings?${query}`);
      setItems(data.items); setCoverage(data.coverage);
    } catch (cause) { setError((cause as Error).message); }
  }, [camera, mode, night]);

  useEffect(() => { void load(); }, [load]);

  async function selectRecording(id: string) {
    try {
      const detail = await ownerFetch<{ video_url: string }>(`/api/research/rap/recordings/${id}`);
      setVideoUrl(detail.video_url);
    } catch (cause) { setError((cause as Error).message); }
  }

  return (
    <main className="mx-auto min-h-screen max-w-7xl space-y-5 bg-zinc-50 px-4 py-6">
      <header>
        <Link href="/labeling/owner/research" className="text-sm text-emerald-700 hover:underline">← 연구 도구</Link>
        <h1 className="mt-1 text-2xl font-semibold text-zinc-950">RAP C500G 녹화 보관함</h1>
        <p className="text-sm text-zinc-500">Mac mini에서 녹화하고 R2까지 검증된 연구 원본을 확인해.</p>
      </header>
      <div className="flex flex-wrap gap-2">
        <select value={mode} onChange={(event) => setMode(event.target.value as RapMode)} className="rounded-lg border bg-white px-3 py-2 text-sm"><option value="production">실제 녹화</option><option value="test">테스트</option></select>
        {mode === 'production' ? <input type="date" value={night} onChange={(event) => setNight(event.target.value)} className="rounded-lg border bg-white px-3 py-2 text-sm" /> : null}
        <select value={camera} onChange={(event) => setCamera(event.target.value)} className="rounded-lg border bg-white px-3 py-2 text-sm"><option value="">카메라 전체</option><option value="cam01">cam01</option><option value="cam02">cam02</option><option value="cam03">cam03</option></select>
      </div>
      {error ? <p className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">{error}</p> : null}
      {videoUrl ? <video src={videoUrl} controls autoPlay className="w-full rounded-2xl bg-black shadow" /> : null}
      <RecordingsView mode={mode} coverage={coverage} items={items} onSelect={(id) => void selectRecording(id)} />
    </main>
  );
}
