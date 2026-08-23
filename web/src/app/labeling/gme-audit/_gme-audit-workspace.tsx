'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useRef, useState } from 'react';
import type { SetStateAction } from 'react';

import Button from '@/components/ui/Button';
import { Card, CardTitle } from '@/components/ui/Card';
import type {
  AuditDetailItem,
  AuditQueueResponse,
  AuditSubmission,
  AuditVerdict,
  NormalizedBox,
} from '@/lib/gmeNegativeAudit';
import { validateAuditSubmission } from '@/lib/gmeNegativeAudit';
import {
  correctAudit,
  getAuditItem,
  getAuditMedia,
  getAuditQueue,
  submitAudit,
} from '@/lib/gmeNegativeAuditApi';
import { ApiError } from '@/lib/labelingApi';
import NormalizedBboxEditor from '../_normalized-bbox-editor';
import ReviewVideo from '../_review-video';

type DraftState = Omit<AuditSubmission, 'verdict'> & { verdict: AuditVerdict | null };
type DraftStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;
export type AuditMediaTracker = { hasLoadedSource: boolean };

const EMPTY_DRAFT: DraftState = { verdict: null, representative_sec: null, bbox: null };
const VERDICTS: ReadonlyArray<{ value: AuditVerdict; label: string }> = [
  { value: 'gecko_present', label: '게코 있음' },
  { value: 'gecko_absent', label: '게코 없음' },
  { value: 'uncertain', label: '판단 어려움' },
  { value: 'media_error', label: '영상 오류' },
];
const DRAFT_KEYS = ['bbox', 'item_id', 'representative_sec', 'v', 'verdict'] as const;
const BOX_KEYS = ['height', 'width', 'x', 'y'] as const;
const MEDIA_RESELECT_NOTICE = '영상을 새로 불러왔어. 대표 시점과 bbox를 다시 선택해줘.';

function exactKeys(value: Record<string, unknown>, expected: readonly string[]): boolean {
  const actual = Object.keys(value).sort();
  const wanted = [...expected].sort();
  return actual.length === wanted.length && actual.every((key, index) => key === wanted[index]);
}

function parseBox(value: unknown): NormalizedBox | null | undefined {
  if (value === null) return null;
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return undefined;
  const row = value as Record<string, unknown>;
  if (!exactKeys(row, BOX_KEYS)) return undefined;
  const values = [row.x, row.y, row.width, row.height];
  if (values.some((part) => typeof part !== 'number' || !Number.isFinite(part))) return undefined;
  const box = { x: row.x as number, y: row.y as number, width: row.width as number, height: row.height as number };
  if (
    box.x < 0 || box.y < 0 || box.width < 0.005 || box.height < 0.005 ||
    box.x + box.width > 1 || box.y + box.height > 1
  ) return undefined;
  return box;
}

export function auditDraftKey(itemId: string): string {
  return `petcam-gme-audit-draft:v1:${encodeURIComponent(itemId)}`;
}

export function parseAuditDraft(raw: string | null, itemId: string, durationSec: number): DraftState | null {
  if (!raw || !Number.isFinite(durationSec) || durationSec <= 0) return null;
  try {
    const value: unknown = JSON.parse(raw);
    if (typeof value !== 'object' || value === null || Array.isArray(value)) return null;
    const row = value as Record<string, unknown>;
    if (!exactKeys(row, DRAFT_KEYS) || row.v !== 1 || row.item_id !== itemId) return null;
    if (row.verdict !== null && !VERDICTS.some((entry) => entry.value === row.verdict)) return null;
    const verdict = row.verdict as AuditVerdict | null;
    const representative = row.representative_sec;
    if (
      representative !== null &&
      (typeof representative !== 'number' || !Number.isFinite(representative) || representative < 0 || representative > durationSec)
    ) return null;
    const bbox = parseBox(row.bbox);
    if (bbox === undefined) return null;
    if (verdict !== 'gecko_present' && (representative !== null || bbox !== null)) return null;
    return { verdict, representative_sec: representative as number | null, bbox };
  } catch {
    return null;
  }
}

export function readAuditDraft(storage: DraftStorage, itemId: string, durationSec: number): DraftState | null {
  const key = auditDraftKey(itemId);
  try {
    const raw = storage.getItem(key);
    const parsed = parseAuditDraft(raw, itemId, durationSec);
    if (raw && !parsed) storage.removeItem(key);
    return parsed;
  } catch {
    return null;
  }
}

export function writeAuditDraft(storage: DraftStorage, itemId: string, state: DraftState): boolean {
  try {
    storage.setItem(auditDraftKey(itemId), JSON.stringify({
      v: 1,
      item_id: itemId,
      verdict: state.verdict,
      representative_sec: state.representative_sec,
      bbox: state.bbox,
    }));
    return true;
  } catch {
    return false;
  }
}

export function clearAuditDraft(storage: DraftStorage, itemId: string): void {
  try { storage.removeItem(auditDraftKey(itemId)); } catch { /* 저장소 실패는 서버 결과를 바꾸지 않는다. */ }
}

export function selectAuditVerdict(state: DraftState, verdict: AuditVerdict): DraftState {
  if (verdict === 'gecko_present') {
    return state.verdict === 'gecko_present' ? state : { verdict, representative_sec: null, bbox: null };
  }
  return { verdict, representative_sec: null, bbox: null };
}

export function beginAuditMediaRequest(
  tracker: AuditMediaTracker,
  draft: DraftState,
): { draft: DraftState; notice: string | null } {
  if (!tracker.hasLoadedSource) return { draft, notice: null };
  const hasGeometry = draft.representative_sec !== null || draft.bbox !== null;
  return hasGeometry
    ? { draft: { ...draft, representative_sec: null, bbox: null }, notice: MEDIA_RESELECT_NOTICE }
    : { draft, notice: null };
}

export function markAuditMediaLoaded(tracker: AuditMediaTracker): void {
  tracker.hasLoadedSource = true;
}

function itemHref(itemId: string): string {
  return `/labeling/gme-audit/${encodeURIComponent(itemId)}`;
}

export function nextAuditHref(queue: AuditQueueResponse, currentItemId: string): string {
  const next = queue.items.find((entry) => !entry.submitted && entry.item_id !== currentItemId);
  return next ? itemHref(next.item_id) : '/labeling/gme-audit';
}

export function auditErrorMessage(cause: unknown, area: 'queue' | 'item' | 'media' | 'save'): string {
  if (cause instanceof ApiError) {
    if (cause.status === 401) return '로그인이 만료됐어. 다시 로그인해줘.';
    if (cause.status === 404) return area === 'item' ? '이 항목을 열 수 없어. 배정을 확인해줘.' : '요청한 영상을 찾을 수 없어.';
    if (cause.status === 410) return '이 점검은 마감됐어. 목록을 새로 확인해줘.';
    if (cause.status === 502 || cause.status === 0) return '잠시 연결하지 못했어. 다시 시도해줘.';
  }
  return area === 'save' ? '저장하지 못했어. 입력을 확인하고 다시 시도해줘.' : '불러오지 못했어. 잠시 뒤 다시 시도해줘.';
}

export function isStaleCorrection(cause: unknown, correction: boolean): boolean {
  return correction && cause instanceof ApiError && cause.status === 409;
}

function QueueView({ data }: { data: AuditQueueResponse }) {
  const next = data.items.find((entry) => !entry.submitted);
  const completed = data.items.filter((entry) => entry.submitted);
  return (
    <div className="min-w-0 space-y-4">
      <div>
        <h1 className="text-xl font-bold tracking-tight text-zinc-950">게코 존재 점검</h1>
        <p className="mt-1 text-sm text-zinc-700">완료 {data.completed} / {data.total}</p>
      </div>

      {data.total === 0 ? (
        <Card><p className="text-sm text-zinc-700">배정된 점검 항목이 없어.</p></Card>
      ) : next ? (
        <Card className="space-y-3">
          <CardTitle>다음 항목</CardTitle>
          <p className="text-sm text-zinc-700">항목 {next.ordinal}</p>
          <Link
            href={itemHref(next.item_id)}
            className="inline-flex min-h-11 w-full items-center justify-center rounded-md bg-emerald-700 px-4 text-sm font-semibold text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500 focus-visible:ring-offset-2"
          >
            다음 항목 열기
          </Link>
        </Card>
      ) : (
        <Card><p className="font-semibold text-emerald-800">모든 점검을 완료했어.</p></Card>
      )}

      {completed.length > 0 && (
        <section aria-labelledby="completed-audit-items" className="space-y-2">
          <h2 id="completed-audit-items" className="text-sm font-semibold text-zinc-900">내가 완료한 항목</h2>
          <ul className="space-y-2">
            {completed.map((entry) => (
              <li key={entry.item_id}>
                <Link
                  href={itemHref(entry.item_id)}
                  className="flex min-h-11 items-center justify-between rounded-lg border border-zinc-200 bg-white px-3 text-sm text-zinc-800 hover:border-zinc-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500"
                >
                  <span>항목 {entry.ordinal}</span>
                  <span className="font-semibold text-emerald-700">항목 {entry.ordinal} 정정</span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

export default function GmeAuditWorkspace({
  itemId,
  initialItem,
  initialQueue,
}: {
  itemId?: string;
  initialItem?: AuditDetailItem;
  initialQueue?: AuditQueueResponse;
}) {
  const router = useRouter();
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const autoMediaRetryRef = useRef(false);
  const successTimerRef = useRef<number | null>(null);
  const initialDraft: DraftState = initialItem?.effective_verdict ? {
    verdict: initialItem.effective_verdict,
    representative_sec: initialItem.effective_representative_sec,
    bbox: initialItem.effective_bbox,
  } : EMPTY_DRAFT;
  const [queue, setQueue] = useState<AuditQueueResponse | null>(initialQueue ?? null);
  const [item, setItem] = useState<AuditDetailItem | null>(initialItem ?? null);
  const [draft, setDraftState] = useState<DraftState>(initialDraft);
  const draftRef = useRef<DraftState>(initialDraft);
  const mediaTrackerRef = useRef<AuditMediaTracker>({ hasLoadedSource: false });
  const mediaRequestGenerationRef = useRef(0);
  const mediaRefreshPendingRef = useRef(false);
  const mediaItemRef = useRef(itemId);
  const [reason, setReason] = useState('');
  const [media, setMedia] = useState<{ url: string; expiresIn: number } | null>(null);
  const [mediaNotice, setMediaNoticeState] = useState<string | null>(null);
  const mediaNoticeRef = useRef<string | null>(null);
  const [mediaRefreshPending, setMediaRefreshPendingState] = useState(false);
  const [loading, setLoading] = useState(!initialItem && !initialQueue);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mediaError, setMediaError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [stale, setStale] = useState(false);

  const setMediaNotice = useCallback((notice: string | null) => {
    mediaNoticeRef.current = notice;
    setMediaNoticeState(notice);
  }, []);

  const setMediaRefreshPending = useCallback((pending: boolean) => {
    mediaRefreshPendingRef.current = pending;
    setMediaRefreshPendingState(pending);
  }, []);

  const setDraft = useCallback((update: SetStateAction<DraftState>) => {
    const next = typeof update === 'function'
      ? (update as (current: DraftState) => DraftState)(draftRef.current)
      : update;
    const nextBox = parseBox(next.bbox);
    draftRef.current = next;
    setDraftState(next);
    if (
      !mediaRefreshPendingRef.current &&
      mediaNoticeRef.current === MEDIA_RESELECT_NOTICE &&
      next.representative_sec !== null &&
      nextBox !== null &&
      nextBox !== undefined
    ) setMediaNotice(null);
  }, [setMediaNotice]);

  const loadMedia = useCallback(async () => {
    if (!itemId) return;
    const requestGeneration = ++mediaRequestGenerationRef.current;
    const isReplacement = mediaTrackerRef.current.hasLoadedSource;
    if (isReplacement) setMediaRefreshPending(true);
    const guarded = beginAuditMediaRequest(mediaTrackerRef.current, draftRef.current);
    if (guarded.notice) {
      setDraft(guarded.draft);
      setMediaNotice(guarded.notice);
    }
    setMediaError(null);
    try {
      const response = await getAuditMedia(itemId);
      if (requestGeneration !== mediaRequestGenerationRef.current) return;
      if (isReplacement) {
        const finalGuard = beginAuditMediaRequest(mediaTrackerRef.current, draftRef.current);
        if (finalGuard.notice) {
          setDraft(finalGuard.draft);
          setMediaNotice(finalGuard.notice);
        }
      }
      markAuditMediaLoaded(mediaTrackerRef.current);
      setMedia({ url: response.url, expiresIn: response.expires_in });
      setMediaRefreshPending(false);
    } catch (cause) {
      if (requestGeneration !== mediaRequestGenerationRef.current) return;
      if (isReplacement) {
        const finalGuard = beginAuditMediaRequest(mediaTrackerRef.current, draftRef.current);
        if (finalGuard.notice) {
          setDraft(finalGuard.draft);
          setMediaNotice(finalGuard.notice);
        }
      }
      setMedia(null);
      setMediaError(auditErrorMessage(cause, 'media'));
      setMediaRefreshPending(false);
    }
  }, [itemId, setDraft, setMediaNotice, setMediaRefreshPending]);

  const loadItem = useCallback(async () => {
    if (!itemId) return;
    setLoading(true);
    setError(null);
    setMediaError(null);
    setSaved(false);
    setStale(false);
    if (mediaItemRef.current !== itemId) {
      mediaItemRef.current = itemId;
      mediaRequestGenerationRef.current += 1;
      mediaTrackerRef.current.hasLoadedSource = false;
      setMediaRefreshPending(false);
      setMedia(null);
    }
    setMediaNotice(null);
    autoMediaRetryRef.current = false;
    try {
      const detail = await getAuditItem(itemId);
      setItem(detail);
      const effective: DraftState = detail.effective_verdict ? {
        verdict: detail.effective_verdict,
        representative_sec: detail.effective_representative_sec,
        bbox: detail.effective_bbox,
      } : EMPTY_DRAFT;
      const restored = readAuditDraft(window.sessionStorage, itemId, detail.duration_sec);
      setDraft(restored ?? effective);
      setReason('');
      if (detail.media_ready) await loadMedia();
      else setMediaError('영상을 아직 재생할 수 없어. 잠시 뒤 다시 시도해줘.');
    } catch (cause) {
      setItem(null);
      setError(auditErrorMessage(cause, 'item'));
    } finally {
      setLoading(false);
    }
  }, [itemId, loadMedia, setDraft, setMediaNotice, setMediaRefreshPending]);

  const loadQueue = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setQueue(await getAuditQueue());
    } catch (cause) {
      setQueue(null);
      setError(auditErrorMessage(cause, 'queue'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (initialItem || initialQueue) return;
    if (itemId) void loadItem();
    else void loadQueue();
  }, [initialItem, initialQueue, itemId, loadItem, loadQueue]);

  useEffect(() => () => {
    if (successTimerRef.current !== null) window.clearTimeout(successTimerRef.current);
  }, []);

  useEffect(() => {
    if (!media || !itemId || initialItem) return;
    const delay = Math.max(1, media.expiresIn - 5) * 1_000;
    const timer = window.setTimeout(() => void loadMedia(), delay);
    return () => window.clearTimeout(timer);
  }, [initialItem, itemId, loadMedia, media]);

  useEffect(() => {
    if (!item || !itemId || initialItem || !draft.verdict) return;
    writeAuditDraft(window.sessionStorage, itemId, draft);
  }, [draft, initialItem, item, itemId]);

  async function save() {
    if (!item || !itemId || busy || mediaRefreshPendingRef.current) return;
    // media refresh는 React 재렌더 전에도 draftRef를 먼저 비운다. 같은 tick의
    // 저장이 이전 화면 closure geometry를 보내지 않도록 최신 ref를 검증한다.
    const currentDraft = draftRef.current;
    setError(null);
    setStale(false);
    if (!currentDraft.verdict) {
      setError('네 판정 중 하나를 선택해줘.');
      return;
    }
    let submission: AuditSubmission;
    try {
      submission = validateAuditSubmission({
        verdict: currentDraft.verdict,
        representative_sec: currentDraft.representative_sec,
        bbox: currentDraft.bbox,
      }, item.duration_sec);
      if (submission.bbox && (submission.bbox.width < 0.005 || submission.bbox.height < 0.005)) {
        throw new Error('small bbox');
      }
    } catch {
      setError(currentDraft.verdict === 'gecko_present'
        ? '게코가 보이는 대표 시점과 bbox를 모두 선택해줘.'
        : '판정 입력을 다시 확인해줘.');
      return;
    }
    const correction = item.revision !== null;
    if (correction && !reason.trim()) {
      setError('정정 이유를 입력해줘.');
      return;
    }

    setBusy(true);
    try {
      if (correction) {
        await correctAudit(itemId, { ...submission, reason: reason.trim(), revision: item.revision! });
      } else {
        await submitAudit(itemId, submission);
      }
      clearAuditDraft(window.sessionStorage, itemId);
      setSaved(true);
      const fresh = await getAuditQueue().catch(() => null);
      const target = fresh ? nextAuditHref(fresh, itemId) : '/labeling/gme-audit';
      successTimerRef.current = window.setTimeout(() => router.replace(target), 650);
    } catch (cause) {
      if (isStaleCorrection(cause, correction)) {
        setStale(true);
        setError('다른 정정이 먼저 저장됐어. 최신 판정을 다시 불러와 확인해줘.');
      } else {
        setError(auditErrorMessage(cause, 'save'));
      }
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <main className="min-w-0 py-8 text-sm text-zinc-600" aria-live="polite">점검 항목을 불러오는 중…</main>;
  if (!itemId) {
    return (
      <main className="min-w-0 py-6">
        {error && !queue ? (
          <Card className="space-y-3">
            <p role="alert" className="text-sm text-rose-700">{error}</p>
            <Button variant="labelingSecondary" onClick={() => void loadQueue()}>다시 시도</Button>
          </Card>
        ) : queue ? <QueueView data={queue} /> : null}
      </main>
    );
  }
  if (!item) {
    return (
      <main className="min-w-0 py-6">
        <Card className="space-y-3">
          <p role="alert" className="text-sm text-rose-700">{error ?? '항목을 불러오지 못했어.'}</p>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            <Button variant="labelingSecondary" onClick={() => void loadItem()}>다시 시도</Button>
            <Link className="inline-flex min-h-11 items-center justify-center text-sm font-semibold text-emerald-700" href="/labeling/gme-audit">목록으로</Link>
          </div>
        </Card>
      </main>
    );
  }

  const correction = item.revision !== null;
  return (
    <main className="min-w-0 space-y-4 py-6">
      <div className="flex min-w-0 items-center justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-xl font-bold tracking-tight text-zinc-950">항목 {item.ordinal}</h1>
          <p className="mt-1 text-sm text-zinc-600">영상 자체만 보고 판단해줘.</p>
        </div>
        <Link className="shrink-0 text-sm font-semibold text-emerald-700 underline" href="/labeling/gme-audit">목록</Link>
      </div>

      <Card padding="sm">
        {media && !mediaRefreshPending ? (
          <NormalizedBboxEditor
            enabled={draft.verdict === 'gecko_present' && !mediaRefreshPending}
            videoRef={videoRef}
            value={draft.bbox}
            onChange={(bbox) => {
              if (mediaRefreshPendingRef.current) return;
              setDraft((current) => ({ ...current, bbox }));
            }}
          >
            <ReviewVideo
              videoRef={videoRef}
              src={media.url}
              getDownload={async () => ({ url: (await getAuditMedia(itemId)).url, filename: 'audit-video.mp4' })}
              onError={() => {
                if (!autoMediaRetryRef.current) {
                  autoMediaRetryRef.current = true;
                  void loadMedia();
                } else {
                  setMediaError('영상 재생이 멈췄어. 다시 불러와줘.');
                }
              }}
            />
          </NormalizedBboxEditor>
        ) : (
          <div className="grid aspect-video place-items-center rounded-lg bg-zinc-100 px-4 text-center text-sm text-zinc-600">
            {mediaRefreshPending ? '영상을 새로 불러오는 중…' : '영상 준비 중…'}
          </div>
        )}
        {mediaNotice && (
          <p role="status" className="mt-3 rounded-lg bg-amber-50 p-3 text-sm font-semibold text-amber-900">
            {mediaNotice}
          </p>
        )}
        {mediaError && (
          <div className="mt-3 flex min-w-0 flex-col items-start gap-2 sm:flex-row sm:items-center sm:justify-between">
            <p role="alert" className="text-sm text-rose-700">{mediaError}</p>
            <Button variant="labelingSecondary" onClick={() => void loadMedia()}>영상 다시 시도</Button>
          </div>
        )}
      </Card>

      <Card className="space-y-4">
        <fieldset>
          <legend className="text-sm font-semibold text-zinc-950">영상에서 게코를 확인할 수 있어?</legend>
          <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
            {VERDICTS.map((entry) => (
              <label
                key={entry.value}
                className={`flex min-h-11 cursor-pointer items-center gap-2 rounded-lg border-2 px-3 text-sm font-semibold focus-within:ring-2 focus-within:ring-emerald-500 ${
                  draft.verdict === entry.value ? 'border-emerald-600 bg-emerald-50 text-emerald-950' : 'border-zinc-200 bg-white text-zinc-800'
                }`}
              >
                <input
                  type="radio"
                  name="audit-verdict"
                  value={entry.value}
                  checked={draft.verdict === entry.value}
                  onChange={() => setDraft((current) => selectAuditVerdict(current, entry.value))}
                  className="accent-emerald-700"
                />
                {entry.label}
              </label>
            ))}
          </div>
        </fieldset>

        {draft.verdict === 'gecko_present' && (
          <div className="space-y-2 rounded-lg border border-emerald-200 bg-emerald-50/50 p-3">
            <Button
              variant="labelingSecondary"
              className="w-full"
              disabled={mediaRefreshPending}
              onClick={() => {
                if (mediaRefreshPendingRef.current) return;
                const second = videoRef.current?.currentTime;
                if (typeof second === 'number' && Number.isFinite(second)) {
                  setDraft((current) => ({ ...current, representative_sec: Math.min(Math.max(second, 0), item.duration_sec) }));
                }
              }}
            >
              현재 재생 위치를 대표 시점으로 사용
            </Button>
            <p className="text-xs text-zinc-700" aria-live="polite">
              {draft.representative_sec === null ? '대표 시점을 아직 선택하지 않았어.' : `${draft.representative_sec.toFixed(2)}초를 선택했어.`}
            </p>
          </div>
        )}

        {correction && (
          <label className="block text-sm font-semibold text-zinc-900">
            정정 이유
            <textarea
              value={reason}
              maxLength={2_000}
              rows={3}
              onChange={(event) => setReason(event.target.value)}
              className="mt-1 block w-full rounded-lg border border-zinc-300 px-3 py-2 text-sm font-normal focus:border-emerald-600 focus:outline-none focus:ring-2 focus:ring-emerald-200"
            />
          </label>
        )}

        <div aria-live="polite">
          {saved && <p role="status" className="mb-2 rounded-lg bg-emerald-50 p-3 text-sm font-semibold text-emerald-800">저장 완료</p>}
          {error && <p role="alert" className="mb-2 rounded-lg bg-rose-50 p-3 text-sm text-rose-700">{error}</p>}
          {stale && <Button
            variant="labelingSecondary"
            className="mb-2 w-full"
            onClick={() => {
              clearAuditDraft(window.sessionStorage, itemId);
              void loadItem();
            }}
          >최신 판정 다시 불러오기</Button>}
        </div>
        <Button variant="labelingPrimary" className="w-full" disabled={busy || saved || mediaRefreshPending} onClick={() => void save()}>
          {busy ? '저장 중…' : correction ? '정정 저장' : '저장'}
        </Button>
      </Card>
    </main>
  );
}
