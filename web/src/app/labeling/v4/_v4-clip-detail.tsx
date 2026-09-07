'use client';

// 라벨링 v4 상세 — 영상 + GME overlay + 하이라이트 1차 판정 + O/X 1클릭 확정(v4 스펙 §2 In 6·7, §5).
//
// 유저 체험: [영상·1차 판정 O/X·근거] → [O 확정 / X 확정 한 번 클릭] → 1차와 같으면 즉시 저장,
// 다르면 이유 칩(선택) 뒤 '저장하고 다음' → 같은 카메라의 다음 '라벨 안 된' 영상으로 자동 이동.
// 이미 사람이 확정한 영상은 읽기 전용(owner 만 correction 으로 재확정). 다른 사람이 먼저 확정해
// 409(already_decided)가 오면 덮어쓰지 않고 안내 뒤 다시 불러온다.

import { useCallback, useEffect, useMemo, useRef, useState, type MutableRefObject } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';

import Button from '@/components/ui/Button';
import { Card, CardTitle } from '@/components/ui/Card';
import { SelectionChip } from '@/components/ui/SelectionControl';
import type { GmeOverlayResponse } from '@/lib/gmeOverlay';
import {
  HIGHLIGHT_CHANGE_REASONS,
  HIGHLIGHT_CHANGE_REASON_DESCRIPTIONS,
  HIGHLIGHT_CHANGE_REASON_LABELS,
  HIGHLIGHT_TRIGGER_LABELS,
  highlightValueLabel,
  isGeckoNotObserved,
  type HighlightChangeReason,
  type HighlightCurrent,
  type HighlightInitial,
} from '@/lib/highlightV4';
import { ApiError, UnauthorizedError } from '@/lib/labelingApi';
import { formatClipCapturedAt } from '@/lib/labelingV2';
import { V4_BEHAVIOR_FLAG_LABEL, behaviorGtPath, v4DetailPath, type V4BehaviorFlag, type V4ClipDetail as V4ClipDetailData } from '@/lib/labelingV4';
import {
  getV4Clip,
  getV4DownloadUrl,
  getV4FileUrl,
  getV4GmeOverlay,
  claimV4View,
  getV4Cameras,
  getV4NextClip,
  setV4BehaviorFlag,
  submitV4Verdict,
} from '@/lib/labelingV4Api';
import {
  PLAYBACK_SPEEDS,
  currentSpanIndex,
  isPlaybackSpeed,
  jumpTargetSec,
  mergeMovingSpans,
  movingTotalSec,
  nextSpanIndex,
  type MovingSpan,
  type PlaybackSpeed,
} from '@/lib/movingIntervals';
import { HOTKEY_LEGEND, mapHotkey, type HotkeyEventLike } from '@/lib/labelingHotkeys';
import { dropPrefetched, peekPrefetched, prefetchClip, warmVideo } from '@/lib/labelingV4Prefetch';
import { applyVerdictToProgress, isProgressStale, readProgress, writeProgress, type V4Progress } from '@/lib/labelingV4Progress';
import { createRequestGeneration } from '@/lib/requestGeneration';
import { GmeVideoOverlay } from '../_gme-overlay';
import ReviewVideo from '../_review-video';
import { useIsOwner } from '../_owner-context';

// 액션 바 껍데기(모바일 하단 고정 / lg 정적). 상세·로딩 화면이 같은 모양을 써서 영상 전환 때 바가 깜빡이지 않는다.
const ACTION_BAR_CLASS =
  'fixed inset-x-0 bottom-0 z-40 space-y-2 border-t border-zinc-200 bg-white/95 px-4 pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] shadow-[0_-4px_12px_rgba(0,0,0,0.06)] backdrop-blur lg:static lg:space-y-3 lg:rounded-xl lg:border lg:bg-white lg:p-5 lg:shadow-sm';

export function Spinner({ className = '' }: { className?: string }) {
  return (
    <svg aria-hidden className={`h-5 w-5 animate-spin ${className}`} viewBox="0 0 24 24" fill="none">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.25" strokeWidth="3" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

// 다음 영상 로딩 화면 — 영상 자리 스켈레톤 + 같은 자리의 액션 바에 진행 문구.
export function V4ClipLoading({ message = '영상 불러오는 중…' }: { message?: string }) {
  return (
    <main className="mx-auto min-w-0 max-w-[1200px] space-y-4 px-4 pt-6 pb-80 lg:pb-6" aria-busy>
      <div className="h-5 w-56 animate-pulse rounded bg-zinc-200" />
      <div className="grid aspect-video w-full place-items-center rounded-lg bg-zinc-900 text-sm text-zinc-300">
        <span className="flex items-center gap-2">
          <Spinner /> {message}
        </span>
      </div>
      <Card className="space-y-3">
        <div className="h-4 w-24 animate-pulse rounded bg-zinc-200" />
        <div className="h-4 w-48 animate-pulse rounded bg-zinc-100" />
      </Card>
      <div className={ACTION_BAR_CLASS}>
        <p role="status" aria-live="polite" className="flex min-h-14 items-center justify-center gap-2 text-sm text-zinc-600 lg:min-h-11">
          <Spinner /> {message}
        </p>
      </div>
    </main>
  );
}

// 사유 칩은 규칙이 O 라고 한 영상을 사람이 X 로 뒤집을 때만 묻는다(하이라이트 스펙 §유저 체험 "X 확정이면 사유 칩").
// 칩 6개는 전부 "왜 하이라이트가 아닌가"라서 X→O 엔 맞는 답이 없고, 규칙이 놓친 건 `x_to_o` 집계가 이미 담는다.
export function needsChangeReason(initial: Pick<HighlightInitial, 'status' | 'value'>, verdict: boolean): boolean {
  return initial.status === 'decided' && initial.value === true && verdict === false;
}

// O→X 사유 칩 목록. `interesting_low_numbers`(X→O 전용)·`gecko_visible_not_highlight`(미관측 셋째 버튼이 자동 부여)는 칩으로 안 보인다.
export const O_TO_X_REASONS = HIGHLIGHT_CHANGE_REASONS.filter((r) => r !== 'interesting_low_numbers' && r !== 'gecko_visible_not_highlight');

// 영상 바로 아래 움직임 내비 줄(순수, SSR 테스트 대상) — 구간 요약 · 다음 움직임 · 속도 · 움직임부터 시작.
// 60초를 다 보지 않고 규칙이 잡은 구간만 보고 판정하게 한다(UX ①, 2026-09-08).
export function MotionNavRow({
  spans,
  currentSec,
  speed,
  autoSkip,
  skipNote,
  gmeState = 'ready',
  notObserved = false,
  onJump,
  onSpeed,
  onToggleAutoSkip,
}: {
  spans: readonly MovingSpan[];
  currentSec: number;
  speed: PlaybackSpeed;
  autoSkip: boolean;
  skipNote: string | null;
  // GME 오버레이 상태: loading(아직 응답 전) / missing(활성 계약 run 없음 = 분석 대기) / ready(run 있음)
  gmeState?: 'loading' | 'missing' | 'ready';
  // run 은 있는데 게코 미관측(visible 0)이라 움직임 0 인 경우 — 정지와 구분해 문구를 낸다.
  notObserved?: boolean;
  onJump: () => void;
  onSpeed: (s: PlaybackSpeed) => void;
  onToggleAutoSkip: () => void;
}) {
  const cur = currentSpanIndex(spans, currentSec);
  const next = nextSpanIndex(spans, currentSec);
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs text-zinc-700" data-testid="motion-nav-row">
      {spans.length > 0 ? (
        <>
          <span className="tabular-nums">
            움직임 {spans.length}구간 · {movingTotalSec(spans).toFixed(1)}초{cur >= 0 ? ` · 지금 ${cur + 1}/${spans.length}` : ''}
          </span>
          <Button variant="labelingSecondary" size="sm" className="min-h-9 touch-manipulation" onClick={onJump} disabled={next === null}>
            ⏭ {next === 0 && currentSec > spans[0].start_sec ? '처음 움직임으로' : `다음 움직임${next !== null ? ` ${next + 1}/${spans.length}` : ''}`}
          </Button>
        </>
      ) : (
        <span className="text-zinc-500" data-testid="motion-nav-empty">
          {gmeState === 'loading'
            ? 'GME 결과 불러오는 중…'
            : gmeState === 'missing'
              ? 'GME 분석 대기 — 이 영상은 현재 계약으로 아직 안 돌았어(움직임 마커 없음)'
              : notObserved
                ? 'GME: 게코 미관측 — 움직임 마커 없음'
                : 'GME: 게코는 보이지만 움직임 없음(정지)'}
        </span>
      )}
      <span className="ml-auto flex items-center gap-1" role="group" aria-label="재생 속도">
        {PLAYBACK_SPEEDS.map((s) => (
          <SelectionChip key={s} pressed={speed === s} tone="neutral" type="button" className="min-h-9 touch-manipulation px-2.5" onClick={() => onSpeed(s)}>
            {s}×
          </SelectionChip>
        ))}
      </span>
      <SelectionChip pressed={autoSkip} tone="success" type="button" className="min-h-9 touch-manipulation" onClick={onToggleAutoSkip} title="영상이 열리면 첫 움직임 0.5초 전으로 건너뛴다">
        움직임부터 시작
      </SelectionChip>
      {skipNote && <span className="w-full text-[11px] text-zinc-500">{skipNote}</span>}
    </div>
  );
}

// "의미있는 행동" 체크 버튼(순수). 하이라이트 O/X 와 독립 — 확정 전후 언제든, 누구든 누를 수 있다.
// 종류(물 마시기·허물·밥…)는 고르지 않는다. 나중에 이 체크만 모아 기존 행동 GT 라벨링 후보로 쓴다.
export function BehaviorFlagButton({
  flag,
  busy,
  onToggle,
  gtHref = null,
}: {
  flag: V4BehaviorFlag;
  busy: boolean;
  onToggle: (next: boolean) => void;
  // 체크된 영상에서 기존 행동 GT 라벨링(motion v3 상세, 승인 사용자 공용)으로.
  gtHref?: string | null;
}) {
  return (
    <div className="flex flex-col gap-1 lg:flex-row lg:items-center lg:gap-3">
    <Button
      type="button"
      variant={flag.flagged ? 'labelingPrimary' : 'labelingSecondary'}
      size="lg"
      aria-pressed={flag.flagged}
      aria-busy={busy || undefined}
      className={`min-h-12 w-full touch-manipulation lg:min-h-11 lg:w-auto ${busy ? 'pointer-events-none' : ''}`}
      data-testid="behavior-flag-button"
      onClick={() => {
        if (!busy) onToggle(!flag.flagged);
      }}
    >
      {busy ? (
        <span className="inline-flex items-center gap-2"><Spinner /> 저장 중…</span>
      ) : flag.flagged ? (
        <span>✨ {V4_BEHAVIOR_FLAG_LABEL} 체크됨{flag.flagged_by_name ? ` · ${flag.flagged_by_name}` : ''} — 눌러서 해제</span>
      ) : (
        <span>✨ {V4_BEHAVIOR_FLAG_LABEL} 보여 (물·허물·밥 등, 종류는 안 골라도 돼)</span>
      )}
    </Button>
    {gtHref && flag.flagged && !busy && (
      <Link href={gtHref} prefetch={false} className="self-end whitespace-nowrap text-xs text-amber-800 underline lg:self-auto">
        행동 라벨링 열기 →
      </Link>
    )}
    </div>
  );
}

// 키보드(UX ④)가 패널 내부 선택 상태를 움직이기 위한 얇은 핸들. 패널이 마운트되면 ref 에 채운다.
export interface PanelKeyboardControls {
  pickVerdict: (verdict: boolean) => void;
  chooseReason: (index: number) => void;
  save: () => void;
}

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
  behaviorFlag,
  progressText = null,
  keyboardRef,
}: {
  initial: HighlightInitial;
  current: HighlightCurrent;
  busy: boolean;
  onDecide: (verdict: boolean, reason: HighlightChangeReason | null) => void;
  // 이미 사람이 확정한 영상에서 '다음 안 된 영상'으로 넘어가는 버튼(없으면 안 그림).
  onNext?: () => void;
  ownerCorrection?: boolean;
  // 바 요약 줄 오른쪽 "오늘 N · 남은 M"(UX ③). 없으면 안 그림.
  progressText?: string | null;
  // PC 단축키 핸들(UX ④). 확정된 영상(읽기 전용)에선 비워 둔다.
  keyboardRef?: MutableRefObject<PanelKeyboardControls | null>;
  // "의미있는 행동" 체크(액션 바 O/X 윗줄). 없으면 안 그림(테스트·구버전 호환).
  behaviorFlag?: { flag: V4BehaviorFlag; busy: boolean; onToggle: (next: boolean) => void; gtHref?: string | null };
}) {
  const [pendingVerdict, setPendingVerdict] = useState<boolean | null>(null);
  // 미관측 1차 판정 화면에서 어느 버튼을 눌렀는지(같은 X 라도 '게코 안 보여'와 '게코 보여·하이라이트 아님'을 구분해 스피너 표시).
  const [pendingChoice, setPendingChoice] = useState<'absent' | 'visible_o' | 'visible_x' | null>(null);
  const [reason, setReason] = useState<HighlightChangeReason | null>(null);
  const notObserved = isGeckoNotObserved(initial);
  const decided = current.source === 'human' && !ownerCorrection;
  const initialLabel =
    initial.status === 'decided' ? (initial.value ? 'O' : 'X') : highlightValueLabel(null, initial.status);
  // 규칙 O 를 X 로 뒤집을 때만 이유 칩을 연다. 그 외(같은 판정·X→O·1차 없음)는 즉시 저장.
  const differs = pendingVerdict === false && needsChangeReason(initial, false);

  const pick = (verdict: boolean, choice: 'absent' | 'visible_o' | 'visible_x' | null = null) => {
    if (busy) return;
    setPendingVerdict(verdict);
    setPendingChoice(choice);
    // 미관측 화면의 '게코 보여·하이라이트 아님'은 X→X 라 사유 칩은 없지만 검출기 누락 신호를 사유로 남긴다(UX ⑥).
    if (!needsChangeReason(initial, verdict)) onDecide(verdict, choice === 'visible_x' ? 'gecko_visible_not_highlight' : null);
  };

  // 저장 중엔 누른 버튼만 스피너+'저장 중…'으로 바꾸고(색 유지) 나머지는 비활성. 부모가 busy 를 내리면 원상복구.
  const saving = (verdict: boolean) => busy && pendingVerdict === verdict;
  const savingLabel = (
    <span className="inline-flex items-center gap-2">
      <Spinner /> 저장 중…
    </span>
  );

  const actionButton = 'min-h-14 flex-1 touch-manipulation lg:min-h-11 lg:flex-none lg:min-w-36';
  // 강조는 기본 1차 판정 쪽, 사용자가 다른 쪽을 골라 이유 칩이 열리면 고른 쪽으로 옮긴다.
  const emphasized = pendingVerdict ?? initial.value;

  // 키보드 핸들 — 미관측 화면에선 O=게코 보여·하이라이트 O, X=게코 안 보여. 사유 번호는 칩 순서(1~5).
  useEffect(() => {
    if (!keyboardRef) return;
    keyboardRef.current = decided
      ? null
      : {
          pickVerdict: (verdict) => pick(verdict, notObserved ? (verdict ? 'visible_o' : 'absent') : null),
          chooseReason: (index) => {
            if (!differs) return;
            const r = O_TO_X_REASONS[index];
            if (r) setReason((cur) => (cur === r ? null : r));
          },
          save: () => {
            if (differs && !busy) onDecide(false, reason);
          },
        };
    return () => {
      keyboardRef.current = null;
    };
  });

  return (
    <>
      <Card className="space-y-3">
        <CardTitle>1차 판정: {initialLabel}{notObserved ? ' (게코 미관측)' : ''}</CardTitle>
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
      <div data-testid="highlight-action-bar" className={ACTION_BAR_CLASS} aria-busy={busy || undefined}>
        <p className="flex items-center gap-2 text-xs text-zinc-600">
          <span className="min-w-0 flex-1 truncate lg:hidden">1차 {initialLabel} · {initial.reason}</span>
          {progressText && <span className="ml-auto shrink-0 tabular-nums text-zinc-500" data-testid="progress-text">{progressText}</span>}
        </p>
        {behaviorFlag && <BehaviorFlagButton flag={behaviorFlag.flag} busy={behaviorFlag.busy} onToggle={behaviorFlag.onToggle} gtHref={behaviorFlag.gtHref} />}
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
        ) : notObserved ? (
          // 규칙이 게코를 못 봤다고 한 영상 — O/X 대신 "안 보여 / 보여"로 묻는다. 세 버튼 모두 즉시 저장.
          // '게코 보여·하이라이트 아님'은 X + 사유 gecko_visible_not_highlight(검출기 누락 신호, UX ⑥).
          <div className="flex flex-col gap-2 lg:flex-row" data-testid="not-observed-choices">
            <Button
              variant="labelingPrimary"
              size="xl"
              className={`${actionButton} ${pendingChoice === 'absent' && busy ? 'pointer-events-none' : ''}`}
              disabled={busy && pendingChoice !== 'absent'}
              aria-busy={(busy && pendingChoice === 'absent') || undefined}
              onClick={() => pick(false, 'absent')}
            >
              {busy && pendingChoice === 'absent' ? savingLabel : '게코 안 보여 · X 확정'}
            </Button>
            <Button
              variant="labelingSecondary"
              size="xl"
              className={`${actionButton} ${pendingChoice === 'visible_o' && busy ? 'pointer-events-none' : ''}`}
              disabled={busy && pendingChoice !== 'visible_o'}
              aria-busy={(busy && pendingChoice === 'visible_o') || undefined}
              onClick={() => pick(true, 'visible_o')}
            >
              {busy && pendingChoice === 'visible_o' ? savingLabel : '게코 보여 · 하이라이트 O'}
            </Button>
            <Button
              variant="labelingSecondary"
              size="xl"
              className={`${actionButton} ${pendingChoice === 'visible_x' && busy ? 'pointer-events-none' : ''}`}
              disabled={busy && pendingChoice !== 'visible_x'}
              aria-busy={(busy && pendingChoice === 'visible_x') || undefined}
              onClick={() => pick(false, 'visible_x')}
            >
              {busy && pendingChoice === 'visible_x' ? savingLabel : '게코 보여 · 하이라이트 아님 X'}
            </Button>
          </div>
        ) : (
          <>
            <div className="flex gap-2">
              <Button
                variant={emphasized === true ? 'labelingPrimary' : 'labelingSecondary'}
                size="xl"
                className={`${actionButton} ${saving(true) ? 'pointer-events-none' : ''}`}
                disabled={busy && !saving(true)}
                aria-busy={saving(true) || undefined}
                onClick={() => pick(true)}
              >
                {saving(true) ? savingLabel : 'O 확정'}
              </Button>
              <Button
                variant={emphasized === false ? 'labelingPrimary' : 'labelingSecondary'}
                size="xl"
                className={`${actionButton} ${saving(false) ? 'pointer-events-none' : ''}`}
                disabled={busy && !saving(false)}
                aria-busy={saving(false) || undefined}
                onClick={() => pick(false)}
              >
                {saving(false) ? savingLabel : 'X 확정'}
              </Button>
            </div>
            {differs && (
              <div className="space-y-2">
                <p className="text-xs text-zinc-600">규칙은 움직임 숫자만 보고 O 라고 했어. 왜 하이라이트가 아닌지 하나 골라줘(선택) — 규칙 조정에 쓰여.</p>
                <div className="flex flex-wrap gap-2">
                  {O_TO_X_REASONS.map((r) => (
                    <SelectionChip
                      key={r}
                      pressed={reason === r}
                      tone="warning"
                      type="button"
                      className="touch-manipulation"
                      title={HIGHLIGHT_CHANGE_REASON_DESCRIPTIONS[r]}
                      disabled={busy}
                      onClick={() => setReason(reason === r ? null : r)}
                    >
                      <span className="mr-1 hidden text-[10px] text-zinc-400 lg:inline">{O_TO_X_REASONS.indexOf(r) + 1}</span>
                      {HIGHLIGHT_CHANGE_REASON_LABELS[r]}
                    </SelectionChip>
                  ))}
                </div>
                <p className="min-h-4 text-xs text-zinc-500" data-testid="reason-description">
                  {reason ? HIGHLIGHT_CHANGE_REASON_DESCRIPTIONS[reason] : '칩을 누르면 뜻이 여기 보여.'}
                </p>
                <Button
                  variant="labelingPrimary"
                  size="xl"
                  className={`min-h-14 w-full touch-manipulation lg:min-h-11 lg:w-auto ${busy ? 'pointer-events-none' : ''}`}
                  aria-busy={busy || undefined}
                  onClick={() => {
                    if (!busy) onDecide(pendingVerdict as boolean, reason);
                  }}
                >
                  {busy ? savingLabel : '저장하고 다음'}
                </Button>
              </div>
            )}
            {busy && (
              <p role="status" aria-live="polite" className="text-center text-xs text-zinc-600">
                저장하고 다음 영상으로 넘어가는 중…
              </p>
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
  // 움직임 내비: 속도·자동 점프 설정은 브라우저에 기억(다음 영상에도 유지). 자동 점프는 영상당 한 번만.
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [speed, setSpeed] = useState<PlaybackSpeed>(1);
  const [autoSkip, setAutoSkip] = useState(true);
  const [skipNote, setSkipNote] = useState<string | null>(null);
  const skippedFor = useRef<string | null>(null);
  const spans = useMemo(() => (overlay?.available ? mergeMovingSpans(overlay.intervals) : []), [overlay]);
  const [busy, setBusy] = useState(false);
  const [flagBusy, setFlagBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  // 진행 수(UX ③): 목록에서 받은 값을 sessionStorage 로 이어받고 확정마다 로컬로 가감. 배정 카메라는 mine 가감용.
  const [progress, setProgress] = useState<V4Progress | null>(null);
  const [myCameraIds, setMyCameraIds] = useState<Set<string>>(() => new Set());
  const keyboardRef = useRef<PanelKeyboardControls | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // clip 전환 중 늦게 도착한 이전 clip 의 응답이 화면을 덮지 않게 세대 번호로 가드한다.
  const gen = useRef(createRequestGeneration());

  const load = useCallback(async () => {
    const g = gen.current.next();
    setErr(null);
    // 프리페치 적중(UX ②): 이전 영상에서 미리 받아 둔 메타·서명 URL·overlay 로 즉시 그린다(로딩 화면 생략).
    // 메타는 그 사이 남이 확정했을 수 있어 뒤에서 한 번 더 받아 덮어쓴다(같은 세대만).
    const cached = peekPrefetched(clipId);
    if (cached) {
      setDetail(cached.detail);
      if (cached.fileUrl) setVideoUrl(cached.fileUrl);
      if (cached.overlay) setOverlay(cached.overlay);
    }
    try {
      const d = await getV4Clip(clipId);
      if (!gen.current.isCurrent(g)) return;
      setDetail(d);
      dropPrefetched(clipId);
      // 서명 URL·overlay 는 메타와 별도로 받는다. 실패해도 1차 판정·확정은 가능해야 한다.
      if (d.media_ready && !cached?.fileUrl) {
        getV4FileUrl(clipId)
          .then((m) => {
            if (gen.current.isCurrent(g)) setVideoUrl(m.url);
          })
          .catch(() => {});
      }
      if (!cached?.overlay) {
        getV4GmeOverlay(clipId)
          .then((o) => {
            if (gen.current.isCurrent(g)) setOverlay(o);
          })
          .catch(() => {});
      }
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
    setSkipNote(null);
    void load();
  }, [load]);

  useEffect(() => {
    const p = readProgress();
    if (p && !isProgressStale(p)) setProgress(p);
    getV4Cameras().then((cams) => setMyCameraIds(new Set(cams.filter((c) => c.assigned).map((c) => c.id)))).catch(() => {});
  }, []);

  useEffect(() => {
    try {
      const s = Number(localStorage.getItem('labeling.v4.speed'));
      if (isPlaybackSpeed(s)) setSpeed(s);
      setAutoSkip(localStorage.getItem('labeling.v4.autoSkip') !== '0');
    } catch {
      // 사생활 모드 등 storage 불가 — 기본값 유지.
    }
  }, []);

  const seekTo = useCallback((sec: number) => {
    const v = videoRef.current;
    if (!v) return;
    v.currentTime = sec;
    setPlaybackTime(sec);
    void v.play().catch(() => {});
  }, []);

  const jumpNext = useCallback(() => {
    const idx = nextSpanIndex(spans, videoRef.current?.currentTime ?? playbackTime);
    if (idx !== null) seekTo(jumpTargetSec(spans[idx]));
  }, [spans, playbackTime, seekTo]);

  const chooseSpeed = useCallback((s: PlaybackSpeed) => {
    setSpeed(s);
    try { localStorage.setItem('labeling.v4.speed', String(s)); } catch { /* storage 불가 */ }
  }, []);

  const toggleAutoSkip = useCallback(() => {
    setAutoSkip((v) => {
      try { localStorage.setItem('labeling.v4.autoSkip', v ? '0' : '1'); } catch { /* storage 불가 */ }
      return !v;
    });
  }, []);

  // 영상이 열리면 첫 움직임 0.5초 전으로(영상당 1회). overlay 와 metadata 중 늦게 오는 쪽에서 실행된다.
  const maybeAutoSkip = useCallback(() => {
    if (!detail || !autoSkip || skippedFor.current === detail.id || spans.length === 0) return;
    const v = videoRef.current;
    if (!v || !Number.isFinite(v.duration) || v.duration <= 0) return;
    const target = jumpTargetSec(spans[0]);
    skippedFor.current = detail.id;
    if (target >= 1) {
      seekTo(target);
      setSkipNote(`첫 움직임 ${spans[0].start_sec.toFixed(1)}초로 건너뜀 — 처음부터 보려면 타임라인을 왼쪽으로`);
    }
  }, [detail, autoSkip, spans, seekTo]);

  useEffect(() => {
    maybeAutoSkip();
  }, [maybeAutoSkip]);

  // 다음 영상 프리페치(UX ②): 상세가 뜨면 같은 카메라의 다음 안 된 영상 메타·서명 URL·overlay 를 미리 받고 영상 바이트를 예열한다.
  // 어떤 영상이 "다음"인지는 이동 시점에 다시 묻는다(goNext) — 캐시는 id 가 같을 때만 쓰인다.
  useEffect(() => {
    if (!detail) return;
    let cancelled = false;
    // "보는 중" 힌트(UX ⑤) — 다른 사람의 다음/이어서 라벨링이 이 영상을 건너뛰게 한다. 실패 무시.
    void claimV4View(detail.id);
    getV4NextClip(detail.id)
      .then(async (next) => {
        if (cancelled || !next) return;
        await prefetchClip(next, { getV4Clip, getV4FileUrl, getV4GmeOverlay });
        if (cancelled) return;
        const peek = peekPrefetched(next);
        if (peek?.fileUrl) warmVideo(next, peek.fileUrl);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [detail]);

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
        if (detail.highlight.current.source !== 'human') {
          setProgress((p) => {
            if (!p) return p;
            const next = applyVerdictToProgress(p, detail.camera_id !== null && myCameraIds.has(detail.camera_id));
            writeProgress(next);
            return next;
          });
        }
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
    [detail, goNext, isOwner, load, myCameraIds],
  );

  // "의미있는 행동" 체크/해제 — O/X 와 독립. 응답의 서버 상태로 덮어쓴다(멱등·첫 체크자 유지).
  const toggleFlag = useCallback(
    async (next: boolean) => {
      if (!detail) return;
      setFlagBusy(true);
      setErr(null);
      try {
        const flag = await setV4BehaviorFlag(detail.id, next);
        setDetail((d) => (d && d.id === detail.id ? { ...d, behavior_flag: flag } : d));
      } catch (cause) {
        setErr(cause instanceof ApiError ? cause.message : (cause as Error).message);
      } finally {
        setFlagBusy(false);
      }
    },
    [detail],
  );

  // PC 단축키(UX ④). 입력 중·조합키는 mapHotkey 가 거른다. Space 는 페이지 스크롤을 막고 재생 토글.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const action = mapHotkey({ key: e.key, ctrlKey: e.ctrlKey, metaKey: e.metaKey, altKey: e.altKey, target: e.target as HotkeyEventLike['target'] });
      if (!action) return;
      e.preventDefault();
      switch (action.kind) {
        case 'verdict': keyboardRef.current?.pickVerdict(action.verdict); break;
        case 'reason': keyboardRef.current?.chooseReason(action.index); break;
        case 'save': keyboardRef.current?.save(); break;
        case 'toggle_play': {
          const v = videoRef.current;
          if (v) { if (v.paused) void v.play().catch(() => {}); else v.pause(); }
          break;
        }
        case 'next_motion': jumpNext(); break;
        case 'toggle_flag':
          if (detail && !flagBusy) void toggleFlag(!detail.behavior_flag.flagged);
          break;
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [jumpNext, toggleFlag, detail, flagBusy]);

  if (err && !detail) {
    return (
      <main className="mx-auto max-w-[1200px] px-4 py-6">
        <Card className="border-rose-200 bg-rose-50 text-sm text-rose-800">{err}</Card>
      </main>
    );
  }
  if (!detail) return <V4ClipLoading message={busy ? '다음 영상 불러오는 중…' : '영상 불러오는 중…'} />;

  return (
    <main className="mx-auto min-w-0 max-w-[1200px] space-y-4 px-4 pt-6 pb-96 lg:pb-6">
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm text-zinc-600">{formatClipCapturedAt(detail.started_at, detail.duration_sec)}</p>
        <Link href="/labeling/all" className="shrink-0 whitespace-nowrap text-sm underline">
          목록
        </Link>
      </div>
      {videoUrl ? (
        <ReviewVideo
          src={videoUrl}
          getDownload={() => getV4DownloadUrl(detail.id)}
          videoRef={videoRef}
          onTimeUpdate={setPlaybackTime}
          onLoadedMetadata={maybeAutoSkip}
          markers={spans}
          markersDurationSec={overlay?.duration_sec || detail.duration_sec || undefined}
          playbackRate={speed}
          overlay={
            overlay?.available ? (
              <GmeVideoOverlay points={overlay.points} intervals={overlay.intervals} currentTimeSec={playbackTime} />
            ) : null
          }
        />
      ) : (
        <Card className="text-sm text-zinc-500">{detail.media_ready ? '영상 준비 중…' : '재생할 수 없는 영상이야.'}</Card>
      )}
      <p className="hidden text-[11px] text-zinc-400 lg:block" data-testid="hotkey-legend">
        단축키: {HOTKEY_LEGEND}
      </p>
      {videoUrl && (
        <MotionNavRow
          spans={spans}
          currentSec={playbackTime}
          speed={speed}
          autoSkip={autoSkip}
          skipNote={skipNote}
          gmeState={overlay === null ? 'loading' : overlay.available ? 'ready' : 'missing'}
          notObserved={isGeckoNotObserved(detail.highlight.initial)}
          onJump={jumpNext}
          onSpeed={chooseSpeed}
          onToggleAutoSkip={toggleAutoSkip}
        />
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
        behaviorFlag={{ flag: detail.behavior_flag, busy: flagBusy, onToggle: toggleFlag, gtHref: behaviorGtPath(detail.id) }}
        progressText={progress ? `오늘 ${progress.labeled_today_me} · 남은 ${progress.unlabeled_all}` : null}
        keyboardRef={keyboardRef}
      />
    </main>
  );
}
