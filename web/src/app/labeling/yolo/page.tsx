'use client';

import { useCallback, useEffect, useState } from 'react';

import { Card } from '@/components/ui/Card';
import type { BlindWorkspace } from '@/lib/yoloContribution';
import { getYoloWorkspace } from '@/lib/yoloContributionApi';
import { ContributionWorkspace } from './_contribution-workspace';

export default function YoloContributionPage() {
  const [workspace, setWorkspace] = useState<BlindWorkspace | null>(null);
  const [error, setError] = useState('');
  const loadWorkspace = useCallback(async () => {
    setError('');
    try {
      setWorkspace(await getYoloWorkspace());
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '작업을 불러오지 못했어.');
    }
  }, []);
  useEffect(() => {
    let active = true;
    getYoloWorkspace().then((value) => { if (active) setWorkspace(value); }).catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : '작업을 불러오지 못했어.'); });
    return () => { active = false; };
  }, []);
  return (
    <main className="min-w-0 space-y-5 px-4 py-6">
      <header><h1 className="text-xl font-semibold">게코 박스 기여</h1><p className="text-sm text-zinc-500">모델을 보기 전에 직접 박스를 만들고, reveal 뒤 차이를 사람 판단으로 수정해.</p></header>
      {error ? <Card className="border-red-200 bg-red-50 text-sm text-red-800">{error}</Card> : null}
      {workspace ? <ContributionWorkspace initial={workspace} key={workspace.next_task?.task_id ?? 'complete'} onCompleted={loadWorkspace} /> : error ? null : <p className="text-sm text-zinc-500">작업을 불러오는 중…</p>}
    </main>
  );
}
