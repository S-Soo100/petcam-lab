'use client';

// 단건 라벨링 — R2 영상 재생 + action 4 메인 + (조건부) lick_target sub + 메모.
//
// 유저 체험 흐름 (CLAUDE.md 유저 시뮬레이션 룰):
// 1. /labeling/{clipId} 진입 → 영상 자동 로드 + 메타 표시
// 2. action 4 메인 버튼 (eating_paste / drinking / moving / unknown) 큰 사각형
// 3. eating_paste 또는 drinking 선택 시 lick_target 6 옵션이 아래에 등장
// 4. 메모는 선택, 더보기로 raw 9 (eating_prey 등) 노출
// 5. 저장 → POST /clips/{id}/labels → 다음 미라벨 클립으로 자동 이동
//
// Why "다음 클립 자동 이동"?
// 라벨러가 50개 라벨링할 때 매번 큐 페이지로 돌아가면 클릭 수 2배. 다음 클립
// /labeling/queue 의 1번째 row 로 즉시 점프하면 흐름 안 깸.

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';

import {
  type ActionType,
  type ClipRow,
  type LabelOut,
  type LabelCreate,
  type LickTargetType,
  type PlaybackUrl,
  ApiError,
  UnauthorizedError,
  createLabel,
  getClip,
  getClipFileUrl,
  getMyLabels,
  getQueue,
} from '@/lib/labelingApi';
import Badge from '@/components/ui/Badge';
import Button from '@/components/ui/Button';
import { Card, CardTitle } from '@/components/ui/Card';

// 4 메인 — spec §2 라벨링 UI 노출.
const MAIN_ACTIONS: { value: ActionType; label: string; hint: string }[] = [
  { value: 'eating_paste', label: '먹기 (paste)', hint: '캐티먹기 / 페이스트 핥기' },
  { value: 'drinking', label: '마시기', hint: '물 핥기' },
  { value: 'moving', label: '이동', hint: '걷기·달리기·자세 변경 등' },
  { value: 'unknown', label: '모르겠음', hint: '판단 불가 / 부분 가림' },
];

// 더보기에 숨김. 호환용 raw 클래스 5개 (총 9 - 4 main = 5).
const RAW_ACTIONS: { value: ActionType; label: string }[] = [
  { value: 'eating_prey', label: '먹기 (사료/곤충)' },
  { value: 'defecating', label: '배변' },
  { value: 'shedding', label: '탈피' },
  { value: 'basking', label: 'basking' },
  { value: 'unseen', label: '안 보임' },
];

// lick_target 6 — eating_paste / drinking 일 때만 노출.
const LICK_TARGETS: { value: LickTargetType; label: string }[] = [
  { value: 'air', label: '허공 (air-lick)' },
  { value: 'dish', label: '그릇' },
  { value: 'floor', label: '바닥' },
  { value: 'wall', label: '벽' },
  { value: 'object', label: '사물' },
  { value: 'other', label: '기타' },
];

const NEEDS_LICK_TARGET: ActionType[] = ['eating_paste', 'drinking'];

export default function LabelClipPage() {
  const router = useRouter();
  const params = useParams<{ clipId: string }>();
  const clipId = params.clipId;

  const [clip, setClip] = useState<ClipRow | null>(null);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [videoUrlError, setVideoUrlError] = useState<string | null>(null);
  const [existing, setExisting] = useState<LabelOut | null>(null);

  const [action, setAction] = useState<ActionType | null>(null);
  const [lickTarget, setLickTarget] = useState<LickTargetType | null>(null);
  const [note, setNote] = useState('');
  const [showRaw, setShowRaw] = useState(false);

  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const lickRequired = useMemo(
    () => (action ? NEEDS_LICK_TARGET.includes(action) : false),
    [action],
  );

  // 클립 + 영상 URL + 본인 기존 라벨 동시 로드.
  const load = useCallback(async () => {
    setBusy(true);
    setErr(null);
    setVideoUrl(null);
    setVideoUrlError(null);

    try {
      const [c, urlResp, labels] = await Promise.allSettled([
        getClip(clipId),
        getClipFileUrl(clipId),
        getMyLabels(clipId),
      ]);

      if (c.status === 'rejected') throw c.reason;
      setClip(c.value);

      if (urlResp.status === 'fulfilled') {
        setVideoUrl((urlResp.value as PlaybackUrl).url);
      } else {
        const e = urlResp.reason;
        if (e instanceof UnauthorizedError) throw e;
        setVideoUrlError(e instanceof ApiError ? e.message : (e as Error).message);
      }

      if (labels.status === 'fulfilled') {
        const me = labels.value[0]; // GET 은 본인 라벨만 (라벨러 케이스도 본인 row 만 의미)
        if (me) {
          setExisting(me);
          setAction(me.action as ActionType);
          setLickTarget((me.lick_target as LickTargetType | null) ?? null);
          setNote(me.note ?? '');
          if (RAW_ACTIONS.some((a) => a.value === me.action)) {
            setShowRaw(true);
          }
        }
      }
    } catch (e) {
      if (e instanceof UnauthorizedError) {
        router.replace('/labeling/login');
        return;
      }
      setErr(e instanceof ApiError ? e.message : (e as Error).message);
    } finally {
      setBusy(false);
    }
  }, [clipId, router]);

  useEffect(() => {
    load();
  }, [load]);

  // action 변경 시 lick_target 호환성 검증.
  useEffect(() => {
    if (!lickRequired) setLickTarget(null);
  }, [lickRequired]);

  async function save() {
    if (!action) return;
    if (lickRequired && !lickTarget) {
      setErr('lick_target 을 골라주세요.');
      return;
    }
    setSaving(true);
    setErr(null);
    try {
      const body: LabelCreate = {
        action,
        lick_target: lickRequired ? lickTarget : null,
        note: note.trim() || null,
      };
      await createLabel(clipId, body);
      // 다음 클립으로 점프 — 큐 1번째 row.
      try {
        const next = await getQueue({ limit: 1 });
        if (next.items[0]) {
          router.push(`/labeling/${next.items[0].id}`);
          return;
        }
      } catch {
        // 큐 호출 실패는 치명적이지 않음 — 그냥 큐 페이지로.
      }
      router.push('/labeling');
    } catch (e) {
      if (e instanceof UnauthorizedError) {
        router.replace('/labeling/login');
        return;
      }
      setErr(e instanceof ApiError ? e.message : (e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  const startedAt = clip
    ? new Date(clip.started_at).toLocaleString('ko-KR', {
        timeZone: 'Asia/Seoul',
        hour12: false,
      })
    : '';

  return (
    <main className="mx-auto max-w-3xl px-6 py-6 space-y-4">
      <div className="flex items-center justify-between gap-3">
        <Link
          href="/labeling"
          className="text-xs text-zinc-500 hover:text-zinc-800"
          prefetch={false}
        >
          ← 큐로
        </Link>
        {existing && <Badge tone="info">기존 라벨 수정 중</Badge>}
      </div>

      {/* 영상 */}
      <Card padding="none" className="overflow-hidden">
        {videoUrl ? (
          <video
            key={videoUrl}
            src={videoUrl}
            controls
            playsInline
            className="block aspect-video w-full bg-black"
          />
        ) : (
          <div className="grid aspect-video w-full place-items-center bg-zinc-100 text-sm text-zinc-500">
            {busy
              ? '영상 로드 중…'
              : videoUrlError
                ? `영상 로드 실패: ${videoUrlError}`
                : '영상 없음'}
          </div>
        )}
      </Card>

      {clip && (
        <div className="flex items-center gap-2 text-xs text-zinc-500">
          <span className="tabular-nums">{startedAt}</span>
          <span>·</span>
          <span>{clip.duration_sec ? `${Math.round(clip.duration_sec)}s` : '?'}</span>
          <span>·</span>
          <span title={clip.id}>{clip.id.slice(0, 8)}</span>
          {clip.has_motion && <Badge tone="success">모션</Badge>}
        </div>
      )}

      {err && (
        <div className="rounded-md bg-red-50 px-4 py-3 text-sm text-red-700 ring-1 ring-inset ring-red-200">
          {err}
        </div>
      )}

      {/* action 4 메인 */}
      <Card padding="md">
        <CardTitle>행동 분류 (action)</CardTitle>
        <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
          {MAIN_ACTIONS.map((a) => {
            const active = action === a.value;
            return (
              <button
                key={a.value}
                type="button"
                onClick={() => setAction(a.value)}
                className={`flex h-20 flex-col items-center justify-center rounded-md border p-2 text-center transition-colors ${
                  active
                    ? 'border-emerald-600 bg-emerald-50 text-emerald-900'
                    : 'border-zinc-200 bg-white text-zinc-700 hover:border-zinc-300 hover:bg-zinc-50'
                }`}
              >
                <span className="text-sm font-semibold">{a.label}</span>
                <span className="mt-0.5 text-xs text-zinc-500">{a.hint}</span>
              </button>
            );
          })}
        </div>

        {/* 더보기 raw 9 */}
        <div className="mt-3">
          <button
            type="button"
            onClick={() => setShowRaw((v) => !v)}
            className="text-xs text-zinc-500 hover:text-zinc-800"
          >
            {showRaw ? '▾ raw 클래스 닫기' : '▸ raw 클래스 더보기 (eating_prey · defecating · …)'}
          </button>
          {showRaw && (
            <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-5">
              {RAW_ACTIONS.map((a) => {
                const active = action === a.value;
                return (
                  <button
                    key={a.value}
                    type="button"
                    onClick={() => setAction(a.value)}
                    className={`flex h-12 items-center justify-center rounded-md border px-2 text-xs transition-colors ${
                      active
                        ? 'border-emerald-600 bg-emerald-50 text-emerald-900'
                        : 'border-zinc-200 bg-white text-zinc-700 hover:border-zinc-300 hover:bg-zinc-50'
                    }`}
                  >
                    {a.label}
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </Card>

      {/* lick_target — 조건부 */}
      {lickRequired && (
        <Card padding="md">
          <CardTitle>핥는 대상 (lick_target)</CardTitle>
          <p className="mt-1 text-xs text-zinc-500">
            paste/drinking 선택 시 필수. air-lick 은 (eating_paste, air) 조합.
          </p>
          <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
            {LICK_TARGETS.map((t) => {
              const active = lickTarget === t.value;
              return (
                <button
                  key={t.value}
                  type="button"
                  onClick={() => setLickTarget(t.value)}
                  className={`flex h-12 items-center justify-center rounded-md border px-2 text-sm transition-colors ${
                    active
                      ? 'border-emerald-600 bg-emerald-50 text-emerald-900'
                      : 'border-zinc-200 bg-white text-zinc-700 hover:border-zinc-300 hover:bg-zinc-50'
                  }`}
                >
                  {t.label}
                </button>
              );
            })}
          </div>
        </Card>
      )}

      {/* 메모 */}
      <Card padding="md">
        <CardTitle>메모 (선택)</CardTitle>
        <textarea
          value={note}
          onChange={(e) => setNote(e.target.value)}
          rows={2}
          maxLength={2000}
          placeholder="애매한 케이스 메모 — 합의 회의용"
          className="mt-2 block w-full resize-y rounded-md border border-zinc-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
        />
      </Card>

      {/* 저장 */}
      <div className="sticky bottom-4 z-10 flex justify-end">
        <Button
          size="lg"
          onClick={save}
          disabled={saving || !action || (lickRequired && !lickTarget)}
        >
          {saving ? '저장 중…' : existing ? '수정 + 다음' : '저장 + 다음'}
        </Button>
      </div>
    </main>
  );
}
