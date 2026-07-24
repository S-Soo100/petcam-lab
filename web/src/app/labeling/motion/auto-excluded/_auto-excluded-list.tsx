'use client';

// Owner 짧은 영상 자동 제외 검수 화면(설계 §4·§5.1).
//
// 검증된 카메라의 장치 오류 후보(quarantined)를 카드로 보여주고, 정상 영상이면 "자동 제외만 해제"한다.
// 해제는 시스템 격리(quarantined→restored)만 되돌리고 사람 판정(triage skip/label)은 절대 바꾸지 않는다.
// 카드만 활성 목록에서 제거하고 다른 탭으로 이동하지 않는다(설계 §4 5). media_deleted 카드는
// `원본 삭제됨 · 메타데이터 보존` + 재생 비활성으로 표시한다.
// 320px 에서 1열(grid-cols-1) + 텍스트 줄바꿈으로 카드가 잘리거나 가로 스크롤을 만들지 않는다.
// raw r2_key/lease/worker/fingerprint/actor 는 API 가 애초에 주지 않는다.

import { useCallback, useEffect, useState } from 'react';

import { ApiError, UnauthorizedError } from '@/lib/labelingApi';
import type { MotionSystemExclusionItem, SystemExclusionState } from '@/lib/labelingV3';
import { getMotionSystemExclusions, restoreMotionSystemExclusion } from '@/lib/labelingV3Api';
import Badge from '@/components/ui/Badge';
import Button from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';

// restore RPC 의 감사 사유(payload). API 시그니처·엔드포인트·payload 는 기존과 동일하게 유지한다.
const RESTORE_REASON = '정상 영상으로 확인되어 자동 제외만 해제';
const RESTORE_NOTICE = '자동 제외를 해제했어. 기존 사람 판정은 유지돼.';

// ── 순수 헬퍼(단위 테스트 대상) ────────────────────────────────────
// 삭제까지 남은 보존 시간 텍스트. delete_after 가 없으면(복구/삭제 완료) null.
export function formatRetentionRemaining(deleteAfter: string | null, now: Date): string | null {
  if (!deleteAfter) return null;
  const ms = new Date(deleteAfter).getTime() - now.getTime();
  if (Number.isNaN(ms)) return null;
  if (ms <= 0) return '삭제 예정 시점이 지났어';
  const hours = Math.ceil(ms / 3_600_000);
  if (hours < 48) return `삭제까지 약 ${hours}시간 남음`;
  return `삭제까지 약 ${Math.ceil(hours / 24)}일 남음`;
}

// 복구 성공 시 해당 clip 카드를 활성 목록에서 제거(다른 탭으로 재이동하지 않는다).
export function removeExclusion(
  items: MotionSystemExclusionItem[],
  clipId: string,
): MotionSystemExclusionItem[] {
  return items.filter((i) => i.clip_id !== clipId);
}

function formatKst(iso: string): string {
  return new Date(iso).toLocaleString('ko-KR', {
    timeZone: 'Asia/Seoul',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

const STATE_LABEL: Record<SystemExclusionState, string> = {
  candidate: '후보',
  quarantined: '자동 제외됨',
  restored: '복구됨',
  media_deleted: '원본 삭제됨',
  deletion_blocked: '삭제 보류',
};

// ── 순수 카드(단위 테스트 대상) ────────────────────────────────────
export function AutoExcludedCard({
  item,
  now,
  onRestore,
  restoring = false,
}: {
  item: MotionSystemExclusionItem;
  now: Date;
  onRestore?: (clipId: string) => void;
  restoring?: boolean;
}) {
  const deleted = item.state === 'media_deleted';
  const retention = formatRetentionRemaining(item.delete_after, now);
  return (
    <Card padding="sm">
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge tone="warning">장치 오류 후보</Badge>
          <Badge tone="neutral">{STATE_LABEL[item.state]}</Badge>
          <span className="break-words text-xs text-zinc-500">규칙 {item.rule_version}</span>
        </div>
        <div className="break-words text-sm font-medium text-zinc-800">
          {item.camera_name || '카메라 미상'}
        </div>
        <div className="tabular-nums text-xs text-zinc-500">{formatKst(item.started_at)}</div>
        <div className="break-words text-xs text-zinc-600">
          실제 {item.duration_sec.toFixed(1)}초 · 표시 {item.displayed_duration_sec}초
        </div>

        {deleted ? (
          <div className="flex flex-col gap-1 text-xs text-zinc-500">
            <p className="font-medium text-zinc-700">원본 삭제됨 · 메타데이터 보존</p>
            {item.media_deleted_at && <p className="break-words">삭제 시각 {formatKst(item.media_deleted_at)}</p>}
            <button
              type="button"
              disabled
              aria-disabled="true"
              className="mt-1 w-full cursor-not-allowed rounded-md border border-zinc-200 bg-zinc-100 px-3 py-2 text-zinc-400"
            >
              재생 불가
            </button>
          </div>
        ) : (
          <>
            {retention && <div className="break-words text-xs text-amber-700">{retention}</div>}
            {item.state === 'quarantined' && (
              <>
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={restoring}
                  onClick={() => onRestore?.(item.clip_id)}
                >
                  {restoring ? '해제 중…' : '자동 제외만 해제'}
                </Button>
                {/* 복구 = 시스템 격리 해제만. 사람 판정(skip/label)은 이 버튼으로 바뀌지 않는다(설계 §5.1). */}
                <p className="break-words text-xs text-zinc-500">
                  기존 사람 판정은 유지돼. 라벨 대상으로 바꾸려면 영상 상세에서 별도로 변경해.
                </p>
              </>
            )}
          </>
        )}
      </div>
    </Card>
  );
}

// ── 순수 그리드/뷰(단위 테스트 대상) ──────────────────────────────
export function AutoExcludedGrid({
  items,
  now,
  onRestore,
  restoringClipId,
}: {
  items: MotionSystemExclusionItem[];
  now: Date;
  onRestore?: (clipId: string) => void;
  restoringClipId?: string | null;
}) {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      {items.map((item) => (
        <AutoExcludedCard
          key={item.clip_id}
          item={item}
          now={now}
          onRestore={onRestore}
          restoring={restoringClipId === item.clip_id}
        />
      ))}
    </div>
  );
}

export function AutoExcludedView({
  items,
  now,
  onRestore,
  restoringClipId,
  emptyLabel,
}: {
  items: MotionSystemExclusionItem[];
  now: Date;
  onRestore?: (clipId: string) => void;
  restoringClipId?: string | null;
  emptyLabel: string;
}) {
  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h1 className="text-lg font-semibold text-zinc-900">자동 제외</h1>
        <p className="break-words text-sm text-zinc-600">
          검증된 카메라에서 장치 오류로 걸러진 영상이야. 정상 영상이면 시스템 격리만 풀 수 있고,
          그때도 기존 사람 판정은 그대로 유지돼. 원본은 R2 에서 지우지 않아.
        </p>
      </div>
      {items.length === 0 ? (
        <Card padding="lg">
          <p className="text-sm text-zinc-600">{emptyLabel}</p>
        </Card>
      ) : (
        <AutoExcludedGrid
          items={items}
          now={now}
          onRestore={onRestore}
          restoringClipId={restoringClipId}
        />
      )}
    </section>
  );
}

// ── client stateful ────────────────────────────────────────────────
export default function AutoExcludedList() {
  const [items, setItems] = useState<MotionSystemExclusionItem[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [loadedOnce, setLoadedOnce] = useState(false);
  const [restoringClipId, setRestoringClipId] = useState<string | null>(null);
  // 보존 잔여 시간 기준 시각 — 렌더마다 흔들리지 않게 한 번만 고정한다.
  const [now] = useState(() => new Date());

  const load = useCallback(async (nextCursor: string | null) => {
    setBusy(true);
    setErr(null);
    try {
      const res = await getMotionSystemExclusions(nextCursor);
      setItems((prev) => (nextCursor ? [...prev, ...res.items] : res.items));
      setCursor(res.next_cursor);
      setHasMore(res.has_more);
      setLoadedOnce(true);
    } catch (e) {
      if (e instanceof UnauthorizedError) setErr('세션이 만료됐어. 다시 로그인해줘.');
      else if (e instanceof ApiError) setErr(e.message);
      else setErr('목록을 불러오지 못했어. 잠시 후 다시 시도해.');
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    void load(null);
  }, [load]);

  // 복구 성공 → 카드만 제거(다른 탭으로 이동하지 않는다).
  const onRestore = useCallback(async (clipId: string) => {
    setRestoringClipId(clipId);
    setErr(null);
    setNotice(null);
    try {
      await restoreMotionSystemExclusion(clipId, RESTORE_REASON);
      setItems((prev) => removeExclusion(prev, clipId));
      // 성공 안내 — "시스템 격리만 해제, 사람 판정은 유지" 를 명시(설계 §5.1).
      setNotice(RESTORE_NOTICE);
    } catch (e) {
      if (e instanceof ApiError) setErr(e.message);
      else setErr('해제에 실패했어. 잠시 후 다시 시도해.');
    } finally {
      setRestoringClipId(null);
    }
  }, []);

  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-4 px-4 py-6">
      {err && (
        <div className="rounded-md bg-red-50 px-4 py-3 text-sm text-red-700 ring-1 ring-inset ring-red-200">
          {err}
        </div>
      )}
      {notice && (
        <div className="rounded-md bg-emerald-50 px-4 py-3 text-sm text-emerald-700 ring-1 ring-inset ring-emerald-200">
          {notice}
        </div>
      )}
      <AutoExcludedView
        items={items}
        now={now}
        onRestore={onRestore}
        restoringClipId={restoringClipId}
        emptyLabel={loadedOnce ? '자동 제외된 영상이 없어.' : '불러오는 중…'}
      />
      {hasMore && (
        <div className="flex justify-center">
          <Button variant="secondary" size="sm" disabled={busy} onClick={() => void load(cursor)}>
            {busy ? '불러오는 중…' : '더 보기'}
          </Button>
        </div>
      )}
    </main>
  );
}
