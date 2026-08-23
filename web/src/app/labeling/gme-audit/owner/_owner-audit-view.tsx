'use client';

import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';

import Button from '@/components/ui/Button';
import { Card, CardTitle } from '@/components/ui/Card';
import NormalizedBboxEditor from '../../_normalized-bbox-editor';
import ReviewVideo from '../../_review-video';
import type { AuditVerdict, NormalizedBox } from '@/lib/gmeNegativeAudit';
import {
  adjudicateAuditItem,
  decideAuditDatasetMembership,
  getAuditOwnerMedia,
  getAuditOwnerOverview,
} from '@/lib/gmeNegativeAuditApi';
import type {
  AuditDatasetDecision,
  AuditOwnerDatasetItem,
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
const FRAME_LOCK_TOLERANCE_SEC = 0.01;
const HAVE_CURRENT_DATA = 2;

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

function DatasetList({
  items,
  onOpen,
}: {
  items: AuditOwnerDatasetItem[];
  onOpen: (item: AuditOwnerDatasetItem) => void;
}) {
  return (
    <section aria-labelledby="owner-audit-dataset" className="space-y-2">
      <h2 id="owner-audit-dataset" className="text-sm font-semibold text-zinc-900">
        Dataset 결정 대기 {items.length}
      </h2>
      {items.length > 0 && (
        <ul className="space-y-2">
          {items.map((item) => (
            <li key={item.item_id}>
              <Card padding="sm" className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0 text-sm">
                  <p className="font-semibold text-zinc-950">항목 {item.ordinal}</p>
                  <p className="text-zinc-600">무작위 negative · {verdictLabel(item.effective_verdict)}</p>
                </div>
                <Button type="button" variant="labelingSecondary" onClick={() => onOpen(item)}>
                  Dataset 결정 열기
                </Button>
              </Card>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

type OwnerEvidenceItem = AuditOwnerPendingItem | AuditOwnerDatasetItem;

export default function OwnerAuditView({ initialOverview }: { initialOverview?: AuditOwnerOverview }) {
  const [overview, setOverview] = useState<AuditOwnerOverview | null>(initialOverview ?? null);
  const [loading, setLoading] = useState(!initialOverview);
  const [selected, setSelected] = useState<OwnerEvidenceItem | null>(null);
  const [mode, setMode] = useState<'adjudication' | 'dataset'>('adjudication');
  const [finalVerdict, setFinalVerdict] = useState<AuditVerdict>('gecko_absent');
  const [representativeSec, setRepresentativeSec] = useState<number | null>(null);
  const [bbox, setBbox] = useState<NormalizedBox | null>(null);
  const [ownerReason, setOwnerReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [adjudicated, setAdjudicated] = useState<{
    item: OwnerEvidenceItem;
    effectiveDigest: string;
    finalVerdict: AuditVerdict;
  } | null>(null);
  const [datasetDecision, setDatasetDecision] = useState<AuditDatasetDecision>('include_candidate');
  const [datasetReason, setDatasetReason] = useState('');
  const [datasetSaved, setDatasetSaved] = useState(false);
  const [mediaUrl, setMediaUrl] = useState<string | null>(null);
  const [mediaReady, setMediaReady] = useState(false);
  const [mediaMetadataLoaded, setMediaMetadataLoaded] = useState(false);
  const [mediaLoadError, setMediaLoadError] = useState<string | null>(null);
  const [frameLock, setFrameLock] = useState<{ generation: number; currentTime: number } | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const mediaGenerationRef = useRef(0);

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

  useEffect(() => {
    if (!selected) {
      mediaGenerationRef.current += 1;
      setMediaUrl(null);
      setMediaReady(false);
      setMediaMetadataLoaded(false);
      setMediaLoadError(null);
      setFrameLock(null);
      return;
    }
    let alive = true;
    const generation = ++mediaGenerationRef.current;
    setMediaUrl(null);
    setMediaReady(false);
    setMediaMetadataLoaded(false);
    setMediaLoadError(null);
    setFrameLock(null);
    setRepresentativeSec(null);
    setBbox(null);
    getAuditOwnerMedia(selected.item_id)
      .then((media) => {
        if (alive && mediaGenerationRef.current === generation) setMediaUrl(media.url);
      })
      .catch((cause) => {
        if (alive && mediaGenerationRef.current === generation) {
          setMediaLoadError(safeError(cause));
          setMediaReady(false);
        }
      });
    return () => { alive = false; };
  }, [selected]);

  async function retryMedia() {
    if (!selected) return;
    const generation = ++mediaGenerationRef.current;
    setMediaUrl(null);
    setMediaReady(false);
    setMediaMetadataLoaded(false);
    setMediaLoadError(null);
    setFrameLock(null);
    setRepresentativeSec(null);
    setBbox(null);
    try {
      const media = await getAuditOwnerMedia(selected.item_id);
      if (mediaGenerationRef.current === generation) setMediaUrl(media.url);
    } catch (cause) {
      if (mediaGenerationRef.current === generation) setMediaLoadError(safeError(cause));
    }
  }

  function invalidateMediaEvidence() {
    mediaGenerationRef.current += 1;
    setMediaUrl(null);
    setMediaReady(false);
    setMediaMetadataLoaded(false);
    setMediaLoadError('영상 재생에 실패했어. 다시 불러와서 시점과 bbox를 새로 선택해줘.');
    setFrameLock(null);
    setRepresentativeSec(null);
    setBbox(null);
  }

  function openItem(item: AuditOwnerPendingItem) {
    setSelected(item);
    setMode('adjudication');
    setFinalVerdict(item.effective_verdict);
    setRepresentativeSec(null);
    setBbox(null);
    setOwnerReason('');
    setAdjudicated(null);
    setDatasetReason('');
    setDatasetSaved(false);
    setError(null);
    setNotice(null);
  }

  function openDatasetItem(item: AuditOwnerDatasetItem) {
    setSelected(item);
    setMode('dataset');
    setFinalVerdict(item.effective_verdict);
    setRepresentativeSec(item.effective_representative_sec);
    setBbox(item.effective_bbox);
    setAdjudicated({ item, effectiveDigest: item.expected_effective_digest, finalVerdict: item.effective_verdict });
    setDatasetDecision(item.effective_verdict === 'gecko_present' ? 'include_candidate' : 'defer');
    setDatasetReason('');
    setDatasetSaved(false);
    setError(null);
    setNotice(null);
  }

  function changeVerdict(verdict: AuditVerdict) {
    setFinalVerdict(verdict);
    setFrameLock(null);
    setRepresentativeSec(null);
    setBbox(null);
  }

  function invalidateFrameEvidence() {
    setFrameLock(null);
    setRepresentativeSec(null);
    setBbox(null);
  }

  function frameLockIsCurrent(): boolean {
    const video = videoRef.current;
    return Boolean(
      frameLock
      && frameLock.generation === mediaGenerationRef.current
      && mediaReady
      && video
      && video.paused
      && !video.seeking
      && video.readyState >= HAVE_CURRENT_DATA
      && Number.isFinite(video.currentTime)
      && Math.abs(video.currentTime - frameLock.currentTime) <= FRAME_LOCK_TOLERANCE_SEC
      && representativeSec === frameLock.currentTime
    );
  }

  function lockCurrentFrame() {
    const video = videoRef.current;
    if (
      !mediaReady
      || !video
      || video.seeking
      || video.readyState < HAVE_CURRENT_DATA
      || !Number.isFinite(video.currentTime)
    ) {
      invalidateFrameEvidence();
      setError('재생 준비가 끝난 정지 프레임에서 다시 선택해줘.');
      return;
    }
    video.pause();
    if (!video.paused || video.seeking) {
      invalidateFrameEvidence();
      setError('영상을 일시정지한 뒤 프레임을 다시 선택해줘.');
      return;
    }
    const currentTime = video.currentTime;
    setFrameLock({ generation: mediaGenerationRef.current, currentTime });
    setRepresentativeSec(currentTime);
    setBbox(null);
    setError(null);
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
    if (!mediaReady) {
      setError('영상이 재생 준비된 뒤 현재 시점과 bbox를 선택해줘.');
      return;
    }
    if (!selected || !('expected_submission_digest' in selected) || ownerReason.trim().length === 0) {
      setError('Owner 판정 이유를 입력해줘.');
      return;
    }
    if (finalVerdict === 'gecko_present' && !frameLockIsCurrent()) {
      invalidateFrameEvidence();
      setError('현재 정지 프레임 잠금이 풀렸어. 대표 프레임과 bbox를 다시 선택해줘.');
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
      setMode('dataset');
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
      setOverview((current) => current ? {
        ...current,
        dataset_decision_eligible: current.dataset_decision_eligible.filter(
          (item) => item.item_id !== adjudicated.item.item_id,
        ),
      } : current);
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
      <DatasetList items={overview.dataset_decision_eligible} onOpen={openDatasetItem} />

      {selected && (
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
          <div className="overflow-hidden rounded-lg bg-black">
            {mediaUrl ? (
              <NormalizedBboxEditor
                enabled={mode === 'adjudication' && finalVerdict === 'gecko_present' && frameLockIsCurrent()}
                videoRef={videoRef}
                value={mode === 'adjudication' ? bbox : null}
                referenceValue={
                  frameLockIsCurrent()
                  && selected.effective_representative_sec !== null
                  && Math.abs(frameLock!.currentTime - selected.effective_representative_sec) <= FRAME_LOCK_TOLERANCE_SEC
                    ? selected.effective_bbox
                    : null
                }
                onChange={(next) => {
                  if (!frameLockIsCurrent()) return;
                  setBbox(next);
                }}
              >
                <ReviewVideo
                  videoRef={videoRef}
                  src={mediaUrl}
                  getDownload={async () => ({
                    url: (await getAuditOwnerMedia(selected.item_id)).url,
                    filename: 'gme-audit-owner-evidence.mp4',
                  })}
                  onLoadedMetadata={() => setMediaMetadataLoaded(true)}
                  onCanPlay={() => {
                    setMediaReady(true);
                    setMediaLoadError(null);
                  }}
                  onPlay={invalidateFrameEvidence}
                  onSeeking={invalidateFrameEvidence}
                  onWaiting={invalidateFrameEvidence}
                  onTimeUpdate={(currentTime) => {
                    if (frameLock && Math.abs(currentTime - frameLock.currentTime) > FRAME_LOCK_TOLERANCE_SEC) {
                      invalidateFrameEvidence();
                    }
                  }}
                  onError={invalidateMediaEvidence}
                />
              </NormalizedBboxEditor>
            ) : (
              <div className="space-y-3 p-4 text-sm text-zinc-200">
                <p>{mediaLoadError ?? 'Owner 증거 영상을 불러오는 중…'}</p>
                {mediaLoadError && (
                  <Button type="button" variant="labelingSecondary" onClick={() => void retryMedia()}>
                    영상 다시 시도
                  </Button>
                )}
              </div>
            )}
          </div>
          {mediaUrl && !mediaReady && (
            <p role="status" className="text-sm text-amber-800">
              {mediaMetadataLoaded ? '첫 프레임을 재생 준비하는 중…' : '영상 정보를 확인하는 중…'}
            </p>
          )}
          {mode === 'adjudication' && !adjudicated && (
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
                  <input aria-label="최종 대표 시점" className="mt-1 min-h-11 w-full rounded-md border border-zinc-300 bg-zinc-50 px-3" type="number" readOnly value={representativeSec ?? ''} />
                </label>
                <Button type="button" variant="labelingSecondary" disabled={!mediaReady} onClick={lockCurrentFrame}>
                  현재 재생 시점 사용
                </Button>
                <p className="text-sm text-zinc-700 sm:col-span-2">
                  영상 위에서 게코를 드래그해 최종 bbox를 선택해줘.
                </p>
              </div>
            )}
            <label className="block text-sm font-semibold text-zinc-900">Owner 판정 이유
              <textarea aria-label="Owner 판정 이유" className="mt-1 min-h-24 w-full rounded-md border border-zinc-300 p-3 font-normal" value={ownerReason} maxLength={2000} onChange={(event) => setOwnerReason(event.target.value)} />
            </label>
            <Button
              type="submit"
              variant="labelingPrimary"
              disabled={busy || !mediaReady || (finalVerdict === 'gecko_present' && (!frameLockIsCurrent() || bbox === null))}
            >Owner 최종 판정 저장</Button>
          </form>
          )}
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
