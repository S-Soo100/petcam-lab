'use client';

import Link from 'next/link';
import { useCallback, useEffect, useState } from 'react';

import Button from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import {
  getBoundaryMediaUrl,
  getBoundaryWorkspace,
  submitBoundaryDecision,
  submitBoundaryEligibility,
} from '@/lib/rbaBoundaryApi';
import type {
  BoundaryDecision,
  BoundaryEligibilityDecision,
  BoundaryWorkspace,
} from '@/lib/rbaBoundaryServer';
import BoundaryPairView from './_boundary-pair-view';
import EligibilityPairView from './_eligibility-pair-view';

export default function BoundaryReviewPage() {
  const [workspace, setWorkspace] = useState<BoundaryWorkspace | null>(null);
  const [urls, setUrls] = useState<{ left: string; right: string } | null>(null);
  const [selected, setSelected] = useState<BoundaryDecision | null>(null);
  const [eligibilitySelected, setEligibilitySelected] = useState<BoundaryEligibilityDecision | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    setUrls(null);
    setSelected(null);
    setEligibilitySelected(null);
    try {
      const next = await getBoundaryWorkspace();
      setWorkspace(next);
      if (next.next_pair) {
        const [left, right] = await Promise.all([
          getBoundaryMediaUrl(next.next_pair.pair_id, 'left'),
          getBoundaryMediaUrl(next.next_pair.pair_id, 'right'),
        ]);
        setUrls({ left: left.url, right: right.url });
      }
    } catch (cause) {
      setError((cause as Error).message);
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  async function submit() {
    if (!workspace?.next_pair || !selected) return;
    setSubmitting(true);
    setError(null);
    try {
      await submitBoundaryDecision(workspace.next_pair.pair_id, selected);
      await load();
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  async function submitEligibility() {
    if (!workspace?.next_pair || !eligibilitySelected) return;
    setSubmitting(true);
    setError(null);
    try {
      await submitBoundaryEligibility(workspace.next_pair.pair_id, eligibilitySelected);
      await load();
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  if (error && !workspace) return <Card className="my-6"><p className="text-sm text-rose-700">{error}</p><Button className="mt-3" onClick={() => void load()}>다시 시도</Button></Card>;
  if (!workspace) return <p className="py-10 text-sm text-zinc-500">이어짐 문제를 불러오는 중…</p>;
  if (!workspace.enabled) return <Card className="my-6"><p className="text-sm text-zinc-700">현재 배정된 이어짐 확인이 없어.</p></Card>;

  return (
    <div className="space-y-4 py-6">
      <div className="flex items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-zinc-950">
            {workspace.mode === 'eligibility' ? '1단계: 영상 자격 확인' : '영상 이어짐 확인'}
          </h1>
          <p className="mt-1 text-sm text-zinc-600">완료 {workspace.completed} / {workspace.total}</p>
        </div>
        {workspace.mode === 'boundary' && workspace.reviewer_role === 'owner' && (
          <Link className="text-sm font-semibold text-emerald-700 underline" href="/labeling/boundary/conflicts">경계 해결</Link>
        )}
      </div>
      {error && <p className="rounded-lg bg-rose-50 p-3 text-sm text-rose-700">{error}</p>}
      {workspace.mode === 'waiting' ? (
        <Card><p className="font-semibold text-zinc-800">Owner의 영상 자격 확인을 기다리고 있어.</p><p className="mt-1 text-sm text-zinc-600">유효한 문제가 확정되면 이어짐 검수가 열려.</p></Card>
      ) : workspace.next_pair && workspace.mode === 'eligibility' ? (
        <EligibilityPairView pair={workspace.next_pair} urls={urls} selected={eligibilitySelected}
          submitting={submitting} onSelect={setEligibilitySelected} onSubmit={() => void submitEligibility()} />
      ) : workspace.next_pair ? (
        <BoundaryPairView pair={workspace.next_pair} urls={urls} selected={selected}
          submitting={submitting} onSelect={setSelected} onSubmit={() => void submit()} />
      ) : (
        <Card><p className="font-semibold text-emerald-800">현재 열린 문제를 모두 끝냈어.</p><p className="mt-1 text-sm text-zinc-600">다음 단계가 열리기 전까지 기다리면 돼.</p></Card>
      )}
    </div>
  );
}
