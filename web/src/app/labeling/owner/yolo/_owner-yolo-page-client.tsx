'use client';

import { useEffect, useState } from 'react';

import { getSupabaseBrowser } from '@/lib/supabaseBrowser';
import { OwnerYoloView } from './_owner-yolo-view';

export function OwnerYoloPageClient({ previewEnabled }: { previewEnabled: boolean }) {
  const [initial, setInitial] = useState<unknown>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    getSupabaseBrowser().auth.getSession().then(({ data }) => fetch('/api/yolo-owner/reviews', { headers: data.session ? { Authorization: `Bearer ${data.session.access_token}` } : {} })).then(async (response) => {
      const payload: unknown = await response.json();
      if (!response.ok) throw new Error('Owner YOLO 현황을 불러오지 못했어.');
      if (active) setInitial(payload);
    }).catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : '현황을 불러오지 못했어.'); });
    return () => { active = false; };
  }, []);
  return (
    <main className="min-w-0 space-y-5 px-4 py-6">
      <header><h1 className="text-xl font-semibold">게코 bbox·모델 연구</h1><p className="text-sm text-zinc-500">사람 revision의 Dataset 승인과 immutable model activation을 수동 관리해.</p></header>
      {error ? <p className="text-sm text-red-700">{error}</p> : initial ? <OwnerYoloView initial={initial} previewEnabled={previewEnabled} /> : <p className="text-sm text-zinc-500">현황을 불러오는 중…</p>}
    </main>
  );
}
