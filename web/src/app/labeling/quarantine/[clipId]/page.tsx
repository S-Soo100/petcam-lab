'use client';

// 격리함 단건 검토 (owner 전용) — 영상 확인 후 결정.
//
// 설계 §4.2~4.3: 헤더(촬영시각·카메라·사유) → 영상 → 결정 버튼 → 최소 provenance 순.
// 결정 후 detail GET 이 잡아둔 next_clip_id 로 자동 이동(같은 탭·같은 필터). null 이면 목록으로.
// 나중에 보기는 PATCH 없이 같은 다음 이동만. 충돌: 409 stale_state → 상세 리로드,
// 409 labeling_started → 안내 후 목록 복귀, 409 state_changed → 목록 복귀(실제 탭에 나타남).
// clipId 가 바뀌면 item/blocked/notice/err/video 상태를 전부 초기화한다(이전 clip 잔상 방지).

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useParams, useRouter, useSearchParams } from 'next/navigation';

import { createRequestGeneration } from '@/lib/requestGeneration';

import {
  type TriageDecision,
  type TriageDetail,
  type TriageTab,
  ApiError,
  UnauthorizedError,
  decideTriage,
  getClipFileUrl,
  getTriageDetail,
} from '@/lib/labelingApi';
import Badge from '@/components/ui/Badge';
import Button from '@/components/ui/Button';
import { Card, CardTitle } from '@/components/ui/Card';

const SKIP_REASSURANCE =
  '일반 라벨링 큐에서 계속 숨겨져. 영상은 삭제되지 않고 언제든 되돌릴 수 있어.';

type VideoState = 'loading' | 'ready' | 'failed';

interface DetailFilters {
  state: TriageTab;
  dateFrom?: string;
  dateTo?: string;
  cameraId?: string;
}

function parseDetailFilters(sp: URLSearchParams): DetailFilters {
  const s = sp.get('state');
  return {
    state: s === 'skipped' || s === 'labeled' ? s : 'pending',
    dateFrom: sp.get('date_from') ?? undefined,
    dateTo: sp.get('date_to') ?? undefined,
    cameraId: sp.get('camera_id') ?? undefined,
  };
}

function buildQuery(f: DetailFilters): string {
  const p = new URLSearchParams();
  p.set('state', f.state);
  if (f.dateFrom) p.set('date_from', f.dateFrom);
  if (f.dateTo) p.set('date_to', f.dateTo);
  if (f.cameraId) p.set('camera_id', f.cameraId);
  return p.toString();
}

export default function QuarantineDetailPage() {
  return (
    <Suspense
      fallback={
        <main className="mx-auto max-w-2xl px-6 py-8 text-sm text-zinc-500">불러오는 중…</main>
      }
    >
      <DetailInner />
    </Suspense>
  );
}

function DetailInner() {
  const router = useRouter();
  const params = useParams<{ clipId: string }>();
  const clipId = params?.clipId ?? '';
  const searchParams = useSearchParams();
  const filters = useMemo(
    () => parseDetailFilters(new URLSearchParams(searchParams.toString())),
    [searchParams],
  );
  const state = filters.state;
  const query = buildQuery(filters);
  const listHref = `/labeling/quarantine?${query}`;

  const [item, setItem] = useState<TriageDetail | null>(null);
  const [nextClipId, setNextClipId] = useState<string | null>(null);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [videoState, setVideoState] = useState<VideoState>('loading');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [blocked, setBlocked] = useState(false); // labeling_started → 결정 불가
  // 요청 세대 guard — item/video 각각. clipId/필터 전환 시 이전 응답이 새 화면을 덮지 않게.
  const itemGen = useRef(createRequestGeneration());
  const videoGen = useRef(createRequestGeneration());

  const load = useCallback(async () => {
    const gen = itemGen.current.next();
    // clipId 전환 시 이전 clip 잔상 초기화(같은 컴포넌트 인스턴스 재사용).
    setItem(null);
    setNextClipId(null);
    setErr(null);
    setNotice(null);
    setBlocked(false);
    try {
      const resp = await getTriageDetail(clipId, state, {
        dateFrom: filters.dateFrom,
        dateTo: filters.dateTo,
        cameraId: filters.cameraId,
      });
      if (!itemGen.current.isCurrent(gen)) return; // 이전 clip 의 늦은 응답 무시
      setItem(resp.item);
      setNextClipId(resp.next_clip_id);
    } catch (e) {
      if (e instanceof UnauthorizedError) {
        router.replace('/labeling/login');
        return;
      }
      if (!itemGen.current.isCurrent(gen)) return; // 이전 clip 의 늦은 오류 무시
      if (e instanceof ApiError && e.status === 409 && e.code === 'state_changed') {
        // URL 탭과 실제 상태가 다름 → 목록으로(해당 clip 은 실제 탭에 나타남).
        router.replace(listHref);
        return;
      }
      if (e instanceof ApiError && e.status === 404) {
        setErr('이 영상은 격리함에 없어. 목록으로 돌아가.');
        return;
      }
      setErr(e instanceof ApiError ? e.message : (e as Error).message);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clipId, state, filters.dateFrom, filters.dateTo, filters.cameraId, router]);

  useEffect(() => {
    load();
  }, [load]);

  // 영상 URL 발급. 최초 로드와 수동 재시도가 같은 세대 guard 를 쓴다(cleanup 반환 안 함).
  // clipId 가 바뀌면 세대가 올라가 이전 요청의 URL/실패 응답이 새 clip 을 덮지 못한다.
  const loadVideo = useCallback(() => {
    const gen = videoGen.current.next();
    setVideoUrl(null);
    setVideoState('loading');
    getClipFileUrl(clipId)
      .then((r) => {
        if (videoGen.current.isCurrent(gen)) setVideoUrl(r.url);
      })
      .catch(() => {
        if (videoGen.current.isCurrent(gen)) setVideoState('failed');
      });
  }, [clipId]);

  useEffect(() => {
    loadVideo();
  }, [loadVideo]);

  const goNext = useCallback(() => {
    if (nextClipId) {
      router.replace(`/labeling/quarantine/${nextClipId}?${query}`);
    } else {
      router.replace(listHref);
    }
  }, [nextClipId, router, query, listHref]);

  const submit = async (decision: TriageDecision) => {
    if (!item) return;
    setBusy(true);
    setErr(null);
    setNotice(null);
    try {
      await decideTriage(clipId, {
        decision,
        expected_updated_at: item.updated_at,
        note: null,
      });
      goNext();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        if (e.code === 'labeling_started') {
          setBlocked(true);
          setNotice('이미 라벨링이 시작되어 격리할 수 없어.');
        } else {
          // stale_state — 다른 화면에서 먼저 변경됨. 상세를 다시 읽는다.
          setNotice('다른 화면에서 먼저 변경됐어. 최신 상태로 새로고침했어.');
          await load();
        }
      } else {
        setErr(e instanceof ApiError ? e.message : (e as Error).message);
      }
    } finally {
      setBusy(false);
    }
  };

  if (err && !item) {
    return (
      <main className="mx-auto max-w-2xl px-6 py-8">
        <Card padding="lg">
          <CardTitle>불러오지 못했어</CardTitle>
          <p className="mt-2 text-sm text-zinc-600">{err}</p>
          <div className="mt-4">
            <Button variant="secondary" onClick={() => router.replace(listHref)}>
              목록으로
            </Button>
          </div>
        </Card>
      </main>
    );
  }

  if (!item) {
    return <main className="mx-auto max-w-2xl px-6 py-8 text-sm text-zinc-500">불러오는 중…</main>;
  }

  const startedAt = item.started_at
    ? new Date(item.started_at).toLocaleString('ko-KR', { timeZone: 'Asia/Seoul', hour12: false })
    : '촬영시각 미상';

  return (
    <main className="mx-auto max-w-2xl px-6 py-8 space-y-5">
      <div className="flex items-center justify-between">
        <Button variant="ghost" size="sm" onClick={() => router.replace(listHref)}>
          ← 목록
        </Button>
      </div>

      {/* 헤더 — 촬영시각·카메라·사유 */}
      <div className="space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="warning">{item.reason_label}</Badge>
          <span className="text-sm tabular-nums text-zinc-700">{startedAt}</span>
        </div>
        <div className="text-xs text-zinc-500">카메라 {item.camera_id ?? '미상'}</div>
      </div>

      {/* 영상 — 발급/재생 실패 시 재시도 버튼, 영구 "불러오는 중" 방지 */}
      <div className="overflow-hidden rounded-lg bg-black">
        {videoState === 'failed' ? (
          <div className="grid aspect-video place-items-center gap-2 text-sm text-zinc-300">
            <span>영상을 불러오지 못했어.</span>
            <Button variant="secondary" size="sm" onClick={loadVideo}>
              다시 시도
            </Button>
          </div>
        ) : videoUrl ? (
          // eslint-disable-next-line jsx-a11y/media-has-caption
          <video
            key={videoUrl}
            controls
            playsInline
            src={videoUrl}
            className="h-auto w-full"
            onLoadedMetadata={() => setVideoState('ready')}
            onError={() => setVideoState('failed')}
          />
        ) : (
          <div className="grid aspect-video place-items-center text-sm text-zinc-400">
            영상 불러오는 중…
          </div>
        )}
      </div>

      {notice && (
        <div className="rounded-md bg-amber-50 px-4 py-3 text-sm text-amber-800 ring-1 ring-inset ring-amber-200">
          {notice}
        </div>
      )}
      {err && (
        <div className="rounded-md bg-red-50 px-4 py-3 text-sm text-red-700 ring-1 ring-inset ring-red-200">
          {err}
        </div>
      )}

      {/* 결정 버튼 — label/skip 은 영상 확인(재생 준비) 전까지 비활성 */}
      {blocked ? (
        <Button variant="secondary" onClick={() => router.replace(listHref)}>
          목록으로 돌아가기
        </Button>
      ) : (
        <DecisionButtons
          state={state}
          busy={busy}
          videoReady={videoState === 'ready'}
          onDecide={submit}
          onLater={goNext}
        />
      )}

      {/* 최소 provenance */}
      <div className="border-t border-zinc-200 pt-3 text-[11px] text-zinc-400">
        <div>정책 버전: {item.policy_version}</div>
        <div>판정 소스: {item.suggestion_source}</div>
      </div>
    </main>
  );
}

function DecisionButtons({
  state,
  busy,
  videoReady,
  onDecide,
  onLater,
}: {
  state: TriageTab;
  busy: boolean;
  videoReady: boolean;
  onDecide: (decision: TriageDecision) => void;
  onLater: () => void;
}) {
  // 영상을 확인하지 못하면 label/skip 판단을 막는다(reset·나중에 보기는 허용).
  const judgeDisabled = busy || !videoReady;
  const gateHint = !videoReady ? (
    <p className="text-xs text-zinc-400">영상을 확인해야 라벨링/스킵을 결정할 수 있어.</p>
  ) : null;

  if (state === 'pending') {
    return (
      <div className="space-y-2">
        <div className="flex flex-wrap gap-2">
          <Button variant="primary" disabled={judgeDisabled} onClick={() => onDecide('label')}>
            라벨링으로 보내기
          </Button>
          <Button variant="danger" disabled={judgeDisabled} onClick={() => onDecide('skip')}>
            라벨링 안 함
          </Button>
          <Button variant="secondary" disabled={busy} onClick={onLater}>
            나중에 보기
          </Button>
        </div>
        <p className="text-xs text-zinc-500">{SKIP_REASSURANCE}</p>
        {gateHint}
      </div>
    );
  }

  // skipped: 반대 결정 = 라벨링으로 보내기, labeled: 반대 결정 = 라벨링 안 함
  const opposite: TriageDecision = state === 'skipped' ? 'label' : 'skip';
  const oppositeLabel = state === 'skipped' ? '라벨링으로 보내기' : '라벨링 안 함';
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        <Button variant="secondary" disabled={busy} onClick={() => onDecide('reset')}>
          결정 초기화
        </Button>
        <Button
          variant={opposite === 'skip' ? 'danger' : 'primary'}
          disabled={judgeDisabled}
          onClick={() => onDecide(opposite)}
        >
          {oppositeLabel}
        </Button>
      </div>
      {opposite === 'skip' && <p className="text-xs text-zinc-500">{SKIP_REASSURANCE}</p>}
      {gateHint}
    </div>
  );
}
