'use client';

// 라벨링 v4 상세 — 영상 + GME overlay + 하이라이트 1차 판정 + O/X 1클릭 확정(v4 스펙 §2 In 6·7, §5).
//
// 유저 체험: [영상·1차 판정 O/X·근거] → [O 확정 / X 확정 한 번 클릭] → 1차와 같으면 즉시 저장,
// 다르면 이유 칩(선택) 뒤 '저장하고 다음' → 같은 카메라의 다음 '라벨 안 된' 영상으로 자동 이동.
// 이미 사람이 확정한 영상은 읽기 전용(owner 만 correction 으로 재확정). 다른 사람이 먼저 확정해
// 409(already_decided)가 오면 덮어쓰지 않고 안내 뒤 다시 불러온다.

import { useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';

import Button from '@/components/ui/Button';
import { Card, CardTitle } from '@/components/ui/Card';
import { SelectionChip } from '@/components/ui/SelectionControl';
import type { GmeOverlayResponse } from '@/lib/gmeOverlay';
import {
  HIGHLIGHT_CHANGE_REASONS,
  HIGHLIGHT_CHANGE_REASON_LABELS,
  HIGHLIGHT_TRIGGER_LABELS,
  highlightValueLabel,
  type HighlightChangeReason,
  type HighlightCurrent,
  type HighlightInitial,
} from '@/lib/highlightV4';
import { ApiError, UnauthorizedError } from '@/lib/labelingApi';
import { formatClipCapturedAt } from '@/lib/labelingV2';
import { v4DetailPath, type V4ClipDetail as V4ClipDetailData } from '@/lib/labelingV4';
import {
  getV4Clip,
  getV4DownloadUrl,
  getV4FileUrl,
  getV4GmeOverlay,
  getV4NextClip,
  submitV4Verdict,
} from '@/lib/labelingV4Api';
import { createRequestGeneration } from '@/lib/requestGeneration';
import { GmeVideoOverlay } from '../_gme-overlay';
import ReviewVideo from '../_review-video';
import { useIsOwner } from '../_owner-context';

// 순수 표시 컴포넌트(SSR 테스트 대상). 1차 판정 카드 + 확정 액션 블록. 확정된 영상은 읽기 전용.
//
// 모바일(lg 미만): 액션 블록을 화면 하단에 고정해 영상 아래를 스크롤하지 않고 엄지로 O/X 를 누른다.
// 1차 판정과 다른 쪽을 고르면 같은 바가 위로 늘어나 이유 칩 + '저장하고 다음'이 붙는다. 카드가
// 스크롤로 사라져도 되게 바 안에 "1차 O · 근거" 한 줄을 같이 둔다(lg 에선 카드 안 정적 배치).
export function HighlightDecisionPanel({
  initial,
  current,
  busy,
  onDecide,
  onNext,
  ownerCorrection = false,
}: {
  initial: HighlightInitial;
  current: HighlightCurrent;
  busy: boolean;
  onDecide: (verdict: boolean, reason: HighlightChangeReason | null) => void;
  // 이미 사람이 확정한 영상에서 '다음 안 된 영상'으로 넘어가는 버튼(없으면 안 그림).
  onNext?: () => void;
  ownerCorrection?: boolean;
}) {
  const [pendingVerdict, setPendingVerdict] = useState<boolean | null>(null);
  const [reason, setReason] = useState<HighlightChangeReason | null>(null);
  const decided = current.source === 'human' && !ownerCorrection;
  const initialLabel =
    initial.status === 'decided' ? (initial.value ? 'O' : 'X') : highlightValueLabel(null, initial.status);
  // 1차 판정과 다른 쪽을 골랐을 때만 이유 칩을 연다(같으면 즉시 저장).
  const differs = pendingVerdict !== null && initial.status === 'decided' && pendingVerdict !== initial.value;

  const pick = (verdict: boolean) => {
    setPendingVerdict(verdict);
    if (initial.status !== 'decided' || initial.value === verdict) onDecide(verdict, null);
  };

  const actionButton = 'min-h-14 flex-1 touch-manipulation lg:min-h-11 lg:flex-none lg:min-w-36';
  // 강조는 기본 1차 판정 쪽, 사용자가 다른 쪽을 골라 이유 칩이 열리면 고른 쪽으로 옮긴다.
  const emphasized = pendingVerdict ?? initial.value;

  return (
    <>
      <Card className="space-y-3">
        <CardTitle>1차 판정: {initialLabel}</CardTitle>
        <p className="text-sm text-zinc-700">{initial.reason}</p>
        {initial.fired.length > 0 && (
          <p className="text-xs text-zinc-500">
            켠 트리거: {initial.fired.map((t) => HIGHLIGHT_TRIGGER_LABELS[t]).join(', ')}
          </p>
        )}
        {initial.shadow.length > 0 && (
          <p className="text-xs text-zinc-400">
            (꺼진 트리거였다면: {initial.shadow.map((t) => HIGHLIGHT_TRIGGER_LABELS[t]).join(', ')})
          </p>
        )}
        {decided && (
          <p className="text-sm text-emerald-800">
            {current.reviewer_name ?? '라벨러'}님이 확정 · {highlightValueLabel(current.value, 'decided')}
          </p>
        )}
      </Card>
      {/* 액션 바 — 모바일은 하단 고정(safe-area 포함), lg 부터는 카드 아래 정적. */}
      <div
        data-testid="highlight-action-bar"
        className="fixed inset-x-0 bottom-0 z-40 space-y-2 border-t border-zinc-200 bg-white/95 px-4 pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] shadow-[0_-4px_12px_rgba(0,0,0,0.06)] backdrop-blur lg:static lg:space-y-3 lg:rounded-xl lg:border lg:bg-white lg:p-5 lg:shadow-sm"
      >
        <p className="truncate text-xs text-zinc-600 lg:hidden">
          1차 {initialLabel} · {initial.reason}
        </p>
        {decided ? (
          <div className="flex gap-2">
            <p className="min-w-0 flex-1 self-center text-sm text-emerald-800">
              {current.reviewer_name ?? '라벨러'}님이 확정 · {highlightValueLabel(current.value, 'decided')}
            </p>
            {onNext && (
              <Button variant="labelingSecondary" size="xl" className={actionButton} onClick={onNext}>
                다음 안 된 영상
              </Button>
            )}
          </div>
        ) : (
          <>
            <div className="flex gap-2">
              <Button
                variant={emphasized === true ? 'labelingPrimary' : 'labelingSecondary'}
                size="xl"
                className={actionButton}
                disabled={busy}
                onClick={() => pick(true)}
              >
                O 확정
              </Button>
              <Button
                variant={emphasized === false ? 'labelingPrimary' : 'labelingSecondary'}
                size="xl"
                className={actionButton}
                disabled={busy}
                onClick={() => pick(false)}
              >
                X 확정
              </Button>
            </div>
            {differs && (
              <div className="space-y-2">
                <p className="text-xs text-zinc-600">1차 판정과 달라. 이유를 하나 고르면 규칙 조정에 쓰여(선택).</p>
                <div className="flex flex-wrap gap-2">
                  {HIGHLIGHT_CHANGE_REASONS.map((r) => (
                    <SelectionChip
                      key={r}
                      pressed={reason === r}
                      tone="warning"
                      type="button"
                      className="touch-manipulation"
                      onClick={() => setReason(reason === r ? null : r)}
                    >
                      {HIGHLIGHT_CHANGE_REASON_LABELS[r]}
                    </SelectionChip>
                  ))}
                </div>
                <Button
                  variant="labelingPrimary"
                  size="xl"
                  className="min-h-14 w-full touch-manipulation lg:min-h-11 lg:w-auto"
                  disabled={busy}
                  onClick={() => onDecide(pendingVerdict as boolean, reason)}
                >
                  저장하고 다음
                </Button>
              </div>
            )}
          </>
        )}
      </div>
    </>
  );
}

export default function V4ClipDetail({ clipId }: { clipId: string }) {
  const router = useRouter();
  const isOwner = useIsOwner();
  const [detail, setDetail] = useState<V4ClipDetailData | null>(null);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [overlay, setOverlay] = useState<GmeOverlayResponse | null>(null);
  const [playbackTime, setPlaybackTime] = useState(0);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // clip 전환 중 늦게 도착한 이전 clip 의 응답이 화면을 덮지 않게 세대 번호로 가드한다.
  const gen = useRef(createRequestGeneration());

  const load = useCallback(async () => {
    const g = gen.current.next();
    setErr(null);
    try {
      const d = await getV4Clip(clipId);
      if (!gen.current.isCurrent(g)) return;
      setDetail(d);
      // 서명 URL·overlay 는 메타와 별도로 받는다. 실패해도 1차 판정·확정은 가능해야 한다.
      if (d.media_ready) {
        getV4FileUrl(clipId)
          .then((m) => {
            if (gen.current.isCurrent(g)) setVideoUrl(m.url);
          })
          .catch(() => {});
      }
      getV4GmeOverlay(clipId)
        .then((o) => {
          if (gen.current.isCurrent(g)) setOverlay(o);
        })
        .catch(() => {});
    } catch (cause) {
      if (!gen.current.isCurrent(g)) return;
      if (cause instanceof UnauthorizedError) {
        router.replace('/labeling/login');
        return;
      }
      setErr(cause instanceof ApiError ? cause.message : (cause as Error).message);
    }
  }, [clipId, router]);

  useEffect(() => {
    setDetail(null);
    setVideoUrl(null);
    setOverlay(null);
    setPlaybackTime(0);
    setNotice(null);
    void load();
  }, [load]);

  // 확정 뒤 같은 카메라의 다음 '라벨 안 된' 영상으로. 없으면 목록으로.
  // 서버가 현재 clip 의 (started_at, id) 를 cursor 로 써서 목록 머리(최신)로 튀지 않고 이어서 간다.
  const goNext = useCallback(async () => {
    if (!detail) return;
    const next = await getV4NextClip(detail.id);
    router.push(next ? v4DetailPath(next) : '/labeling/all');
  }, [detail, router]);

  const decide = useCallback(
    async (verdict: boolean, reason: HighlightChangeReason | null) => {
      if (!detail) return;
      setBusy(true);
      setErr(null);
      try {
        await submitV4Verdict(detail.id, {
          verdict,
          change_reason: reason,
          kind: detail.highlight.current.source === 'human' && isOwner ? 'correction' : 'initial',
        });
        await goNext();
      } catch (cause) {
        // 다른 사람이 먼저 확정(부분 유니크 잠금) — 덮어쓰지 않고 안내 뒤 최신 상태를 다시 보여준다.
        if (cause instanceof ApiError && cause.code === 'already_decided') {
          setNotice(cause.message);
          await load();
        } else {
          setErr(cause instanceof ApiError ? cause.message : (cause as Error).message);
        }
      } finally {
        setBusy(false);
      }
    },
    [detail, goNext, isOwner, load],
  );

  if (err && !detail) {
    return (
      <main className="mx-auto max-w-[1200px] px-4 py-6">
        <Card className="border-rose-200 bg-rose-50 text-sm text-rose-800">{err}</Card>
      </main>
    );
  }
  if (!detail) return <main className="mx-auto max-w-[1200px] px-4 py-6 text-sm text-zinc-500">불러오는 중…</main>;

  return (
    <main className="mx-auto min-w-0 max-w-[1200px] space-y-4 px-4 pt-6 pb-80 lg:pb-6">
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm text-zinc-600">{formatClipCapturedAt(detail.started_at, detail.duration_sec)}</p>
        <Link href="/labeling/all" className="text-sm underline">
          목록
        </Link>
      </div>
      {videoUrl ? (
        <ReviewVideo
          src={videoUrl}
          getDownload={() => getV4DownloadUrl(detail.id)}
          onTimeUpdate={setPlaybackTime}
          overlay={
            overlay?.available ? (
              <GmeVideoOverlay points={overlay.points} intervals={overlay.intervals} currentTimeSec={playbackTime} />
            ) : null
          }
        />
      ) : (
        <Card className="text-sm text-zinc-500">{detail.media_ready ? '영상 준비 중…' : '재생할 수 없는 영상이야.'}</Card>
      )}
      {notice && <Card className="border-amber-200 bg-amber-50 text-sm text-amber-900">{notice}</Card>}
      {err && <Card className="border-rose-200 bg-rose-50 text-sm text-rose-800">{err}</Card>}
      <HighlightDecisionPanel
        initial={detail.highlight.initial}
        current={detail.highlight.current}
        busy={busy}
        onDecide={decide}
        onNext={detail.highlight.current.source === 'human' && !isOwner ? goNext : undefined}
        ownerCorrection={isOwner && detail.highlight.current.source === 'human'}
      />
    </main>
  );
}
