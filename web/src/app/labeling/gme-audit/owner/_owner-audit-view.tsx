'use client';

import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';

import Button from '@/components/ui/Button';
import { Card, CardTitle } from '@/components/ui/Card';
import type { AuditVerdict, NormalizedBox } from '@/lib/gmeNegativeAudit';
import {
  adjudicateAuditItem,
  decideAuditDatasetMembership,
  getAuditOwnerOverview,
} from '@/lib/gmeNegativeAuditApi';
import type {
  AuditDatasetDecision,
  AuditOwnerOverview,
  AuditOwnerPendingItem,
} from '@/lib/gmeNegativeAuditApi';
import { ApiError } from '@/lib/labelingApi';

const VERDICTS: ReadonlyArray<{ value: AuditVerdict; label: string }> = [
  { value: 'gecko_present', label: '게코 있음' },
  { value: 'gecko_absent', label: '게코 없음' },
  { value: 'uncertain', label: '판단 어려움' },
  { value: 'media_error', label: '영상 오류' },
];
const DECISIONS: ReadonlyArray<{ value: AuditDatasetDecision; label: string }> = [
  { value: 'include_candidate', label: '후보 포함' },
  { value: 'exclude_duplicate', label: '중복 제외' },
  { value: 'exclude_holdout', label: 'holdout 제외' },
  { value: 'exclude_quality', label: '품질 제외' },
  { value: 'defer', label: '결정 보류' },
];

function verdictLabel(verdict: AuditVerdict): string {
  return VERDICTS.find((entry) => entry.value === verdict)?.label ?? verdict;
}

function stratumLabel(stratum: AuditOwnerPendingItem['stratum']): string {
  return stratum === 'random_negative' ? '무작위 negative' : '양성 control';
}

function safeError(cause: unknown): string {
  if (cause instanceof ApiError) {
    if (cause.status === 401 || cause.status === 403) return 'Owner 로그인을 확인해줘.';
    if (cause.status === 404) return '점검 항목을 찾을 수 없어. 목록을 새로 확인해줘.';
    if (cause.status === 410) return '이미 처리됐거나 점검이 종료됐어. 목록을 새로 확인해줘.';
    if (cause.status === 502 || cause.status === 0) return '잠시 연결하지 못했어. 다시 시도해줘.';
  }
  return '저장하지 못했어. 입력을 확인하고 다시 시도해줘.';
}

function Summary({ overview }: { overview: AuditOwnerOverview }) {
  return (
    <section aria-labelledby="owner-audit-summary" className="space-y-2">
      <h2 id="owner-audit-summary" className="text-sm font-semibold text-zinc-900">진행 현황</h2>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Card className="space-y-1" padding="sm">
          <p className="text-xs text-zinc-600">전체</p>
          <p className="font-semibold text-zinc-950">완료 {overview.completed} / {overview.total}</p>
        </Card>
        <Card className="space-y-1" padding="sm">
          <p className="text-xs text-zinc-600">무작위 표본</p>
          <p className="font-semibold text-zinc-950">
            무작위 negative {overview.random_negative.completed} / {overview.random_negative.total}
          </p>
        </Card>
        <Card className="space-y-1" padding="sm">
          <p className="text-xs text-zinc-600">주의력 확인</p>
          <p className="font-semibold text-zinc-950">
            양성 control {overview.positive_control.completed} / {overview.positive_control.total}
          </p>
        </Card>
      </div>
    </section>
  );
}

function PendingList({
  items,
  onOpen,
}: {
  items: AuditOwnerPendingItem[];
  onOpen: (item: AuditOwnerPendingItem) => void;
}) {
  return (
    <section aria-labelledby="owner-audit-pending" className="space-y-2">
      <h2 id="owner-audit-pending" className="text-sm font-semibold text-zinc-900">
        Owner 판정 대기 {items.length}
      </h2>
      {items.length === 0 ? (
        <Card padding="sm"><p className="text-sm text-emerald-800">추가 판정이 필요한 항목이 없어.</p></Card>
      ) : (
        <ul className="space-y-2">
          {items.map((item) => (
            <li key={item.item_id}>
              <Card padding="sm" className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0 text-sm">
                  <p className="font-semibold text-zinc-950">항목 {item.ordinal}</p>
                  <p className="text-zinc-600">{stratumLabel(item.stratum)} · {verdictLabel(item.effective_verdict)}</p>
                </div>
                <Button type="button" variant="labelingSecondary" onClick={() => onOpen(item)}>
                  검토 열기
                </Button>
              </Card>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export default function OwnerAuditView({ initialOverview }: { initialOverview?: AuditOwnerOverview }) {
  const [overview, setOverview] = useState<AuditOwnerOverview | null>(initialOverview ?? null);
  const [loading, setLoading] = useState(!initialOverview);
  const [selected, setSelected] = useState<AuditOwnerPendingItem | null>(null);
  const [finalVerdict, setFinalVerdict] = useState<AuditVerdict>('gecko_absent');
  const [representativeSec, setRepresentativeSec] = useState<number | null>(null);
  const [bbox, setBbox] = useState<NormalizedBox | null>(null);
  const [ownerReason, setOwnerReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [adjudicated, setAdjudicated] = useState<{
    item: AuditOwnerPendingItem;
    effectiveDigest: string;
    finalVerdict: AuditVerdict;
  } | null>(null);
  const [datasetDecision, setDatasetDecision] = useState<AuditDatasetDecision>('include_candidate');
  const [datasetReason, setDatasetReason] = useState('');
  const [datasetSaved, setDatasetSaved] = useState(false);

  useEffect(() => {
    if (initialOverview) return;
    let alive = true;
    (async () => {
      try {
        const loaded = await getAuditOwnerOverview();
        if (alive) setOverview(loaded);
      } catch (cause) {
        if (alive) setError(safeError(cause));
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [initialOverview]);

  function openItem(item: AuditOwnerPendingItem) {
    setSelected(item);
    setFinalVerdict(item.effective_verdict);
    setRepresentativeSec(item.effective_representative_sec);
    setBbox(item.effective_bbox);
    setOwnerReason('');
    setAdjudicated(null);
    setDatasetReason('');
    setDatasetSaved(false);
    setError(null);
    setNotice(null);
  }

  function changeVerdict(verdict: AuditVerdict) {
    setFinalVerdict(verdict);
    if (verdict === 'gecko_present') {
      setRepresentativeSec(selected?.effective_verdict === 'gecko_present' ? selected.effective_representative_sec : null);
      setBbox(selected?.effective_verdict === 'gecko_present' ? selected.effective_bbox : null);
    } else {
      setRepresentativeSec(null);
      setBbox(null);
    }
  }

  async function reloadAfterStale() {
    const latest = await getAuditOwnerOverview();
    setOverview(latest);
    setSelected(null);
    setAdjudicated(null);
    setNotice('판정이 바뀌어서 최신 대기 목록을 다시 불러왔어.');
  }

  async function submitAdjudication(event: FormEvent) {
    event.preventDefault();
    if (!selected || ownerReason.trim().length === 0) {
      setError('Owner 판정 이유를 입력해줘.');
      return;
    }
    if (finalVerdict === 'gecko_present' && (representativeSec === null || bbox === null)) {
      setError('게코 있음 판정에는 대표 시점과 bbox가 필요해.');
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = await adjudicateAuditItem(selected.item_id, {
        final_verdict: finalVerdict,
        representative_sec: finalVerdict === 'gecko_present' ? representativeSec : null,
        bbox: finalVerdict === 'gecko_present' ? bbox : null,
        reason: ownerReason.trim(),
        expected_submission_digest: selected.expected_submission_digest,
      });
      setOverview((current) => current ? {
        ...current,
        needs_adjudication: current.needs_adjudication.filter((item) => item.item_id !== selected.item_id),
      } : current);
      setAdjudicated({ item: selected, effectiveDigest: result.effective_digest, finalVerdict });
      setDatasetDecision(finalVerdict === 'gecko_present' ? 'include_candidate' : 'defer');
      setNotice('Owner 판정을 append-only로 저장했어.');
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 409) {
        try {
          await reloadAfterStale();
        } catch (reloadCause) {
          setError(safeError(reloadCause));
        }
      } else {
        setError(safeError(cause));
      }
    } finally {
      setBusy(false);
    }
  }

  async function submitDatasetDecision(event: FormEvent) {
    event.preventDefault();
    if (!adjudicated || adjudicated.item.stratum === 'positive_control' || datasetReason.trim().length === 0) {
      setError('Dataset 결정 이유를 입력해줘.');
      return;
    }
    if (datasetDecision === 'include_candidate' && adjudicated.finalVerdict !== 'gecko_present') {
      setError('게코 있음으로 확정된 항목만 후보에 포함할 수 있어.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await decideAuditDatasetMembership(adjudicated.item.item_id, {
        decision: datasetDecision,
        reason: datasetReason.trim(),
        expected_effective_digest: adjudicated.effectiveDigest,
      });
      setDatasetSaved(true);
      setNotice('Dataset 결정을 append-only로 저장했어.');
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 409) {
        try {
          await reloadAfterStale();
        } catch (reloadCause) {
          setError(safeError(reloadCause));
        }
      } else {
        setError(safeError(cause));
      }
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <main className="min-w-0 px-4 py-8 text-sm text-zinc-600" aria-live="polite">Owner 점검 현황을 불러오는 중…</main>;
  if (!overview) {
    return (
      <main className="min-w-0 space-y-3 px-4 py-8">
        <p role="alert" className="text-sm text-rose-800">{error ?? 'Owner 점검 현황을 불러오지 못했어.'}</p>
        <Button type="button" variant="labelingSecondary" onClick={() => window.location.reload()}>다시 시도</Button>
      </main>
    );
  }

  return (
    <main className="min-w-0 space-y-5 px-4 py-6">
      <header>
        <h1 className="text-xl font-bold tracking-tight text-zinc-950">GME 점검 Owner 판정</h1>
        <p className="mt-1 text-sm text-zinc-600">추가 확인이 필요한 사람 판정만 검토해.</p>
      </header>
      <Summary overview={overview} />
      <PendingList items={overview.needs_adjudication} onOpen={openItem} />

      {selected && !adjudicated && (
        <Card className="min-w-0 space-y-4">
          <CardTitle>항목 {selected.ordinal} Owner 확인</CardTitle>
          <div className="rounded-lg bg-zinc-50 p-3 text-sm text-zinc-800">
            <p>{stratumLabel(selected.stratum)}</p>
            <p className="font-semibold">검수자 유효 판정: {verdictLabel(selected.effective_verdict)}</p>
            {selected.effective_representative_sec !== null && <p>대표 시점 {selected.effective_representative_sec}초</p>}
            {selected.effective_bbox && (
              <p>bbox x {selected.effective_bbox.x}, y {selected.effective_bbox.y}, 폭 {selected.effective_bbox.width}, 높이 {selected.effective_bbox.height}</p>
            )}
          </div>
          <form data-action="adjudicate" className="space-y-4" onSubmit={submitAdjudication}>
            <fieldset className="space-y-2">
              <legend className="text-sm font-semibold text-zinc-900">최종 판정</legend>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {VERDICTS.map((entry) => (
                  <label key={entry.value} className="flex min-h-11 items-center gap-2 rounded-md border border-zinc-300 px-3 text-sm">
                    <input type="radio" name="owner-final-verdict" value={entry.value} checked={finalVerdict === entry.value} onChange={() => changeVerdict(entry.value)} />
                    {entry.label}
                  </label>
                ))}
              </div>
            </fieldset>
            {finalVerdict === 'gecko_present' && (
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                <label className="text-sm text-zinc-800">대표 시점(초)
                  <input className="mt-1 min-h-11 w-full rounded-md border border-zinc-300 px-3" type="number" min="0" max={selected.duration_sec} step="0.01" value={representativeSec ?? ''} onChange={(event) => setRepresentativeSec(event.target.value === '' ? null : Number(event.target.value))} />
                </label>
                <p className="text-xs text-zinc-600 sm:self-end">검수자 bbox를 기준으로 확인하고 필요하면 수치를 바로잡아.</p>
                {(['x', 'y', 'width', 'height'] as const).map((key) => (
                  <label key={key} className="text-sm text-zinc-800">bbox {key}
                    <input className="mt-1 min-h-11 w-full rounded-md border border-zinc-300 px-3" type="number" min="0" max="1" step="0.001" value={bbox?.[key] ?? ''} onChange={(event) => setBbox((current) => ({ x: current?.x ?? 0, y: current?.y ?? 0, width: current?.width ?? 0, height: current?.height ?? 0, [key]: Number(event.target.value) }))} />
                  </label>
                ))}
              </div>
            )}
            <label className="block text-sm font-semibold text-zinc-900">Owner 판정 이유
              <textarea aria-label="Owner 판정 이유" className="mt-1 min-h-24 w-full rounded-md border border-zinc-300 p-3 font-normal" value={ownerReason} maxLength={2000} onChange={(event) => setOwnerReason(event.target.value)} />
            </label>
            <Button type="submit" variant="labelingPrimary" disabled={busy}>Owner 최종 판정 저장</Button>
          </form>
        </Card>
      )}

      {adjudicated?.item.stratum === 'positive_control' && (
        <Card padding="sm"><p className="text-sm text-zinc-700">양성 control은 Dataset 후보 결정 대상이 아니야.</p></Card>
      )}

      {adjudicated?.item.stratum === 'random_negative' && !datasetSaved && (
        <Card className="space-y-4">
          <CardTitle>Dataset 후보 결정</CardTitle>
          <form data-action="dataset-decision" className="space-y-3" onSubmit={submitDatasetDecision}>
            <label className="block text-sm font-semibold text-zinc-900">결정
              <select aria-label="Dataset 결정" className="mt-1 min-h-11 w-full rounded-md border border-zinc-300 bg-white px-3 font-normal" value={datasetDecision} onChange={(event) => setDatasetDecision(event.target.value as AuditDatasetDecision)}>
                {DECISIONS.filter((entry) => entry.value !== 'include_candidate' || adjudicated.finalVerdict === 'gecko_present').map((entry) => (
                  <option key={entry.value} value={entry.value}>{entry.label}</option>
                ))}
              </select>
            </label>
            <label className="block text-sm font-semibold text-zinc-900">Dataset 결정 이유
              <textarea aria-label="Dataset 결정 이유" className="mt-1 min-h-24 w-full rounded-md border border-zinc-300 p-3 font-normal" value={datasetReason} maxLength={2000} onChange={(event) => setDatasetReason(event.target.value)} />
            </label>
            <Button type="submit" variant="labelingPrimary" disabled={busy}>Dataset 결정 저장</Button>
          </form>
        </Card>
      )}

      <div aria-live="polite" className="space-y-2">
        {notice && <p role="status" className="text-sm font-semibold text-emerald-800">{notice}</p>}
        {error && <p role="alert" className="text-sm text-rose-800">{error}</p>}
      </div>
    </main>
  );
}
