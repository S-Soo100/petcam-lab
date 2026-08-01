'use client';

import { useCallback, useEffect, useState } from 'react';

import Button from '@/components/ui/Button';
import { Card, CardTitle } from '@/components/ui/Card';
import {
  getBoundaryConflicts,
  getBoundaryMediaUrl,
  resolveBoundaryConflict,
} from '@/lib/rbaBoundaryApi';
import type { BoundaryConflict, BoundaryConflicts, BoundaryDecision } from '@/lib/rbaBoundaryServer';
import ReviewVideo from '../../_review-video';

const LABEL: Record<BoundaryDecision, string> = {
  same_event: '같은 사건', different_event: '다른 사건', uncertain: '잘 모르겠음',
};

function ConflictCard({ item, onDone }: { item: BoundaryConflict; onDone: () => void }) {
  const [urls, setUrls] = useState<{ left: string; right: string } | null>(null);
  const [decision, setDecision] = useState<BoundaryDecision | null>(null);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function loadMedia() {
    setBusy(true); setError(null);
    try {
      const [left, right] = await Promise.all([
        getBoundaryMediaUrl(item.pair_id, 'left'), getBoundaryMediaUrl(item.pair_id, 'right'),
      ]);
      setUrls({ left: left.url, right: right.url });
    } catch (cause) { setError((cause as Error).message); }
    finally { setBusy(false); }
  }
  async function resolve() {
    if (!decision || reason.trim().length < 3) return;
    setBusy(true); setError(null);
    try { await resolveBoundaryConflict(item.pair_id, decision, reason); onDone(); }
    catch (cause) { setError((cause as Error).message); setBusy(false); }
  }
  return (
    <Card className="space-y-4">
      <div><CardTitle>문제 {item.ordinal}</CardTitle><p className="mt-1 text-xs text-zinc-500">두 최초 판정이 다르거나 ‘잘 모르겠음’이 포함됐어.</p></div>
      <div className="grid grid-cols-2 gap-2 text-sm">
        {item.submissions.map((submission) => (
          <div key={submission.reviewer_role} className="rounded-lg bg-zinc-50 p-3">
            <p className="text-xs text-zinc-500">{submission.reviewer_role === 'owner' ? '내 최초 판정' : '상대 최초 판정'}</p>
            <p className="mt-1 font-semibold">{LABEL[submission.decision]}</p>
          </div>
        ))}
      </div>
      {!urls ? <Button variant="secondary" disabled={busy} onClick={() => void loadMedia()}>영상 A/B 보기</Button> : (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <ReviewVideo src={urls.left} />
          <ReviewVideo src={urls.right} />
        </div>
      )}
      <div className="grid grid-cols-3 gap-2">
        {(Object.keys(LABEL) as BoundaryDecision[]).map((value) => (
          <button key={value} type="button" onClick={() => setDecision(value)} className={`rounded-lg border-2 p-2 text-xs font-semibold ${decision === value ? 'border-emerald-600 bg-emerald-50' : 'border-zinc-200'}`}>{LABEL[value]}</button>
        ))}
      </div>
      <textarea className="min-h-24 w-full rounded-lg border border-zinc-300 p-3 text-sm" value={reason} onChange={(event) => setReason(event.target.value)} placeholder="왜 이렇게 최종 결정했는지 세 글자 이상 적어줘" />
      {error && <p className="text-sm text-rose-700">{error}</p>}
      <Button variant="labelingPrimary" className="w-full" disabled={busy || !decision || reason.trim().length < 3} onClick={() => void resolve()}>최종 판정 저장</Button>
    </Card>
  );
}

export default function BoundaryConflictsPage() {
  const [data, setData] = useState<BoundaryConflicts | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    setError(null); getBoundaryConflicts().then(setData).catch((cause) => setError((cause as Error).message));
  }, []);
  useEffect(load, [load]);
  return (
    <div className="space-y-4 py-6">
      <div><h1 className="text-xl font-bold">경계 해결</h1><p className="mt-1 text-sm text-zinc-600">두 최초 판정이 다르거나 불확실한 문제만 최종 결정해.</p></div>
      {error && <Card><p className="text-sm text-rose-700">{error}</p><Button className="mt-3" onClick={load}>다시 시도</Button></Card>}
      {!data && !error && <p className="text-sm text-zinc-500">불러오는 중…</p>}
      {data?.total === 0 && <Card><p className="text-sm text-zinc-600">현재 해결할 문제가 없어.</p></Card>}
      {data?.items.map((item) => <ConflictCard key={item.pair_id} item={item} onDone={load} />)}
    </div>
  );
}
