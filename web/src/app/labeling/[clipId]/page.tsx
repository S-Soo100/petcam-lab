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
import { useParams, useRouter, useSearchParams } from 'next/navigation';
import Link from 'next/link';

import {
  type ActionType,
  type ClipRow,
  type InferenceOut,
  type LabelOut,
  type LabelCreate,
  type LickTargetType,
  type PlaybackUrl,
  ApiError,
  UnauthorizedError,
  createLabel,
  getClip,
  getClipFileUrl,
  getInference,
  getMyLabels,
  getQueue,
} from '@/lib/labelingApi';
import { getSupabaseBrowser } from '@/lib/supabaseBrowser';
import Badge from '@/components/ui/Badge';
import Button from '@/components/ui/Button';
import { Card, CardTitle } from '@/components/ui/Card';
import { useToast } from '@/components/Toast';
import { useIsOwner } from '../_owner-context';

// 4 메인 — spec §2 라벨링 UI 노출.
const MAIN_ACTIONS: { value: ActionType; label: string; hint: string }[] = [
  { value: 'eating_paste', label: '먹기 (paste)', hint: '캐티먹기 / 페이스트 핥기' },
  { value: 'drinking', label: '마시기', hint: '물 핥기' },
  { value: 'moving', label: '이동', hint: '걷기·달리기·자세 변경 등' },
  { value: 'unknown', label: '모르겠음', hint: '판단 불가 / 부분 가림' },
];

// 더보기에 숨김. raw 클래스 (main 4 외) + OOD hand_feeding.
// hand_feeding 은 OOD(사람/도구 개입) — C-2 에서 별도 체크박스 UX 로 승격 예정.
const RAW_ACTIONS: { value: ActionType; label: string }[] = [
  { value: 'hand_feeding', label: '사람 급여 (손/도구)' },
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

// 옛 BEHAVIOR_CLASSES 9 raw — behavior_logs 에 mirror 가능한 action 들.
// 'unknown' (behavior_labels 의 4 main 중 하나) 은 여기 없음 → mirror skip.
const MIRRORABLE_ACTIONS: ReadonlySet<ActionType> = new Set([
  'eating_paste',
  'eating_prey',
  'drinking',
  'defecating',
  'shedding',
  'basking',
  'hiding',
  'moving',
  'unseen',
  'hand_feeding',
] as ActionType[]);

// behavior_labels 저장 후 dashboard·results 가 보는 옛 behavior_logs 에도 mirror.
// lick_target 은 behavior_logs 에 칼럼이 없어 notes 에 prefix 로 박음 — 사용자가 결과 페이지에서 읽을 수 있게.
// 실패해도 throw 안 함 — 메인 라벨 저장은 성공이니 mirror 실패는 silent (콘솔 경고만).
async function mirrorToBehaviorLogs(
  clipId: string,
  action: ActionType,
  lickTarget: LickTargetType | null,
  userNote: string,
): Promise<void> {
  if (!MIRRORABLE_ACTIONS.has(action)) return;
  const composedNote = [
    userNote.trim(),
    lickTarget ? `[lick_target=${lickTarget}]` : '',
  ]
    .filter(Boolean)
    .join('\n')
    .trim();
  try {
    const resp = await fetch('/api/label', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        clip_id: clipId,
        action,
        notes: composedNote || undefined,
      }),
    });
    if (!resp.ok) {
      console.warn('mirror to behavior_logs failed', resp.status, await resp.text());
    }
  } catch (e) {
    console.warn('mirror to behavior_logs threw', e);
  }
}

export default function LabelClipPage() {
  const router = useRouter();
  const params = useParams<{ clipId: string }>();
  const searchParams = useSearchParams();
  const clipId = params.clipId;
  const toast = useToast();
  const isOwner = useIsOwner();

  // ?from=<path> — owner 가 results/queue 등에서 진입 시 저장 후 복귀할 path.
  // open redirect 방지: 내부 path 만 (`/` 시작, `//` 는 protocol-relative 라 차단).
  const fromRaw = searchParams?.get('from') ?? null;
  const back =
    fromRaw && fromRaw.startsWith('/') && !fromRaw.startsWith('//') ? fromRaw : null;
  const backLabel = back?.startsWith('/results')
    ? '← 결과로'
    : back?.startsWith('/queue')
      ? '← 큐로 (F2)'
      : '← 큐로';

  const [clip, setClip] = useState<ClipRow | null>(null);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [videoUrlError, setVideoUrlError] = useState<string | null>(null);
  const [existing, setExisting] = useState<LabelOut | null>(null);
  // 검수 섹션 (owner 일 때만 채워짐)
  const [otherLabels, setOtherLabels] = useState<LabelOut[]>([]);
  const [inference, setInference] = useState<InferenceOut | null>(null);
  const [meId, setMeId] = useState<string | null>(null);
  // override confirm 모달 — null 이면 닫힘.
  const [overrideTarget, setOverrideTarget] = useState<LabelOut | null>(null);

  const [action, setAction] = useState<ActionType | null>(null);
  const [lickTarget, setLickTarget] = useState<LickTargetType | null>(null);
  const [note, setNote] = useState('');
  const [showRaw, setShowRaw] = useState(false);

  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  // 삭제 — owner only. 별도 state 로 saving/overrideTarget 과 충돌 방지.
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);

  // 영상 재생 불가 → 폼 disable.
  // r2_key 없으면 백엔드가 410 또는 local fallback 줄 수 있는데 prod 라벨링 웹은 cross-origin.
  // videoUrlError 또는 r2_key=null 이면 라벨 입력 불가 안내.
  const videoUnavailable =
    !!videoUrlError || (clip !== null && !clip.r2_key);

  const lickRequired = useMemo(
    () => (action ? NEEDS_LICK_TARGET.includes(action) : false),
    [action],
  );

  // 클립 + 영상 URL + 라벨 (owner 면 모든 라벨러, 라벨러면 본인) + VLM 추론 동시 로드.
  // 검수 섹션은 owner 일 때만 — labeled_by !== 본인 인 row 가 1개+ 있으면 owner 임이 자연스럽게 추론.
  // 추론 호출은 라벨러일 땐 403 → 무시 (별도 에러 표시 안 함).
  const load = useCallback(async () => {
    setBusy(true);
    setErr(null);
    setVideoUrl(null);
    setVideoUrlError(null);

    try {
      // 본인 user_id — labels 응답을 본인/타인 분리할 때 필요.
      const sb = getSupabaseBrowser();
      const {
        data: { session },
      } = await sb.auth.getSession();
      const myId = session?.user?.id ?? null;
      setMeId(myId);

      const [c, urlResp, labels, inf] = await Promise.allSettled([
        getClip(clipId),
        getClipFileUrl(clipId),
        getMyLabels(clipId),
        getInference(clipId),
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
        const all = labels.value;
        const own = myId ? all.find((l) => l.labeled_by === myId) ?? null : (all[0] ?? null);
        const others = myId ? all.filter((l) => l.labeled_by !== myId) : [];
        setOtherLabels(others);
        if (own) {
          setExisting(own);
          setAction(own.action as ActionType);
          setLickTarget((own.lick_target as LickTargetType | null) ?? null);
          setNote(own.note ?? '');
          if (RAW_ACTIONS.some((a) => a.value === own.action)) {
            setShowRaw(true);
          }
        } else {
          setExisting(null);
        }
      }

      // inference: owner 면 row, 라벨러면 403 → null. 다른 에러도 조용히 null 처리.
      if (inf.status === 'fulfilled') {
        setInference(inf.value);
      } else {
        const e = inf.reason;
        if (e instanceof UnauthorizedError) throw e;
        setInference(null);
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
    if (!action || videoUnavailable) return;
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
      // dashboard·results 가 보는 옛 behavior_logs 에 mirror INSERT.
      // backend behavior_labels 만 가면 대시보드 GT 카운트 안 늘어남 (테이블 분리).
      // unknown 은 BEHAVIOR_CLASSES 9 raw 에 없어 skip — sample 라벨러 'unseen' 권장.
      await mirrorToBehaviorLogs(clipId, action, lickRequired ? lickTarget : null, note);
      // toast Provider 가 RootLayout 에 있어 router.push 후에도 살아있음.
      toast.show('저장됨', 'success');
      // from 있으면 (results/queue 등 owner 진입) 그쪽으로 복귀, 없으면 다음 미라벨 클립.
      if (back) {
        router.push(back);
        return;
      }
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
      const msg = e instanceof ApiError ? e.message : (e as Error).message;
      setErr(msg);
      toast.show(`저장 실패: ${msg}`, 'error');
    } finally {
      setSaving(false);
    }
  }

  // owner override — 본인 폼 값으로 다른 라벨러 라벨 덮어쓰기.
  // confirm 모달의 "확인" 시 호출. 본인 폼의 action/lick_target/note 를 그대로 박는 게
  // 자연스러움 (시나리오 2: "alice 의 라벨이 맞다고 판단 → 그 값으로 덮어쓰기").
  async function applyOverride() {
    if (!overrideTarget || !action) return;
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
        labeled_by: overrideTarget.labeled_by,
      };
      await createLabel(clipId, body);
      // override 도 mirror — owner 가 결정한 GT 가 dashboard 에 반영되어야 함.
      await mirrorToBehaviorLogs(clipId, action, lickRequired ? lickTarget : null, note);
      setOverrideTarget(null);
      toast.show('덮어쓰기 완료', 'success');
      // 페이지 갱신 — 다른 라벨러 row 가 새 값으로 보여야.
      await load();
    } catch (e) {
      if (e instanceof UnauthorizedError) {
        router.replace('/labeling/login');
        return;
      }
      const msg = e instanceof ApiError ? e.message : (e as Error).message;
      setErr(msg);
      toast.show(`덮어쓰기 실패: ${msg}`, 'error');
    } finally {
      setSaving(false);
    }
  }

  // owner 영구 삭제 — DELETE /api/clips/[id] 호출.
  // R2 객체 + behavior_logs/labels + camera_clips 한 번에 정리.
  async function handleDelete() {
    if (!isOwner || deleting) return;
    setDeleting(true);
    try {
      const sb = getSupabaseBrowser();
      const {
        data: { session },
      } = await sb.auth.getSession();
      if (!session) {
        router.replace('/labeling/login');
        return;
      }
      const resp = await fetch(`/api/clips/${clipId}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${session.access_token}` },
      });
      if (!resp.ok) {
        const j = await resp.json().catch(() => ({}));
        throw new Error(j.error ?? `삭제 실패 (${resp.status})`);
      }
      toast.show('삭제됨', 'success');
      setDeleteOpen(false);
      // 큐로 복귀 — back 있으면 들어온 곳, 없으면 라벨링 큐.
      router.push(back ?? '/labeling');
    } catch (e) {
      toast.show(`삭제 실패: ${(e as Error).message}`, 'error');
      setDeleting(false);
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
          href={back ?? '/labeling'}
          className="text-xs text-zinc-500 hover:text-zinc-800"
          prefetch={false}
        >
          {backLabel}
        </Link>
        <div className="flex items-center gap-2">
          {existing && <Badge tone="info">기존 라벨 수정 중</Badge>}
          {isOwner && (
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setDeleteOpen(true)}
              className="!text-red-600 hover:!bg-red-50"
              title="이 클립과 라벨을 영구 삭제"
            >
              삭제
            </Button>
          )}
        </div>
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

      {/* 영상 재생 불가 안내 (spec §3-D) — r2 미업로드 또는 file/url 실패 */}
      {videoUnavailable && !busy && (
        <div className="rounded-md bg-amber-50 px-4 py-3 text-sm text-amber-800 ring-1 ring-inset ring-amber-200">
          이 클립은 R2 에 업로드되지 않았거나 인코딩 실패했습니다. 라벨링 불가.{' '}
          <Link href="/labeling" className="font-medium underline">
            큐로 돌아가기
          </Link>
        </div>
      )}

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
            {showRaw ? '▾ 더보기 닫기' : '▸ 더보기 (사람 급여 · eating_prey · defecating · …)'}
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

      {/* OOD 안내 — hand_feeding 선택 시 (C-2). 라벨러가 OOD 임을 인지하고 분할 라벨하도록. */}
      {action === 'hand_feeding' && (
        <div className="rounded-md bg-orange-50 px-4 py-3 text-sm text-orange-800 ring-1 ring-inset ring-orange-200">
          🟧 <strong>OOD 영상</strong> — 사람 손·스푼·시린지·핀셋이 frame 에 보이는 급여.
          운영 환경(사람 부재)엔 없는 장면이라 <strong>P0 학습에서 제외</strong>됩니다. 도구가
          빠진 뒤 도마뱀이 혼자 먹는 구간이 있으면, 그 부분은 별도 클립처럼 eating_prey /
          eating_paste 로 라벨하세요.
        </div>
      )}

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

      {/* 검수 섹션 — owner 전용 (otherLabels 1개+ 또는 inference 있음).
          백엔드가 라벨러에겐 본인 row 만 + inference 403 반환 → 자연스럽게 안 뜸. */}
      {(otherLabels.length > 0 || inference) && (
        <Card padding="md">
          <CardTitle>검수 (owner)</CardTitle>
          <p className="mt-1 text-xs text-zinc-500">
            VLM 추론 + 다른 라벨러 라벨 비교. "이 라벨로 수정" 클릭 시 본인 폼 값으로
            그 라벨러의 라벨이 덮어써집니다.
          </p>

          {inference && (
            <div className="mt-3 rounded-md border border-sky-200 bg-sky-50 p-3 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone="info">RBA 1.0 추론</Badge>
                <span className="font-semibold text-sky-900">{inference.action}</span>
                {inference.confidence !== null && (
                  <span className="text-xs text-sky-700">
                    conf {inference.confidence.toFixed(2)}
                  </span>
                )}
                {inference.vlm_model && (
                  <span className="text-[10px] text-sky-600" title={inference.vlm_model}>
                    {inference.vlm_model}
                  </span>
                )}
              </div>
              {inference.reasoning && (
                <p className="mt-1 text-xs text-sky-800">{inference.reasoning}</p>
              )}
            </div>
          )}

          {otherLabels.length > 0 && (
            <div className="mt-3 space-y-2">
              <div className="text-xs font-medium text-zinc-600">
                다른 라벨러 라벨 ({otherLabels.length})
              </div>
              {otherLabels.map((lab) => {
                const labeledAt = new Date(lab.labeled_at).toLocaleString('ko-KR', {
                  timeZone: 'Asia/Seoul',
                  hour12: false,
                });
                return (
                  <div
                    key={lab.id}
                    className="flex items-start justify-between gap-3 rounded-md border border-zinc-200 bg-white p-3"
                  >
                    <div className="min-w-0 flex-1 text-sm">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span
                          className="font-mono text-xs text-zinc-500"
                          title={lab.labeled_by}
                        >
                          {lab.labeled_by.slice(0, 8)}
                        </span>
                        <span className="font-semibold text-zinc-900">
                          {lab.action}
                          {lab.lick_target ? ` (${lab.lick_target})` : ''}
                        </span>
                      </div>
                      <div className="mt-0.5 text-xs text-zinc-500 tabular-nums">
                        {labeledAt}
                      </div>
                      {lab.note && (
                        <div className="mt-1 text-xs text-zinc-600">"{lab.note}"</div>
                      )}
                    </div>
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => setOverrideTarget(lab)}
                      disabled={!action || saving || videoUnavailable}
                      title={
                        !action
                          ? '본인 폼에서 action 을 먼저 골라야 합니다'
                          : '본인 폼 값으로 이 라벨을 덮어씁니다'
                      }
                    >
                      이 라벨로 수정
                    </Button>
                  </div>
                );
              })}
            </div>
          )}
        </Card>
      )}

      {/* 저장 */}
      <div className="sticky bottom-4 z-10 flex justify-end">
        <Button
          size="lg"
          onClick={save}
          disabled={
            saving || !action || (lickRequired && !lickTarget) || videoUnavailable
          }
          title={videoUnavailable ? '영상 재생 불가 — 라벨링 불가' : undefined}
        >
          {saving ? '저장 중…' : existing ? '수정 + 다음' : '저장 + 다음'}
        </Button>
      </div>

      {/* override confirm 모달 */}
      {overrideTarget && (
        <OverrideConfirmModal
          target={overrideTarget}
          formAction={action}
          formLickTarget={lickRequired ? lickTarget : null}
          formNote={note}
          saving={saving}
          onCancel={() => setOverrideTarget(null)}
          onConfirm={applyOverride}
        />
      )}

      {/* 삭제 confirm 모달 */}
      {deleteOpen && clip && (
        <DeleteConfirmModal
          clipShortId={clip.id.slice(0, 8)}
          deleting={deleting}
          onCancel={() => !deleting && setDeleteOpen(false)}
          onConfirm={handleDelete}
        />
      )}
    </main>
  );
}

// ─────────────────────────────────────────────────────────────────
// Override confirm 모달 — owner 가 다른 라벨러 라벨 덮어쓰기
// ─────────────────────────────────────────────────────────────────

function OverrideConfirmModal({
  target,
  formAction,
  formLickTarget,
  formNote,
  saving,
  onCancel,
  onConfirm,
}: {
  target: LabelOut;
  formAction: ActionType | null;
  formLickTarget: LickTargetType | null;
  formNote: string;
  saving: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const labelerShort = target.labeled_by.slice(0, 8);
  const newDisplay = formAction
    ? formAction + (formLickTarget ? ` (${formLickTarget})` : '')
    : '?';
  const oldDisplay =
    target.action + (target.lick_target ? ` (${target.lick_target})` : '');

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-black/40 px-4"
      onClick={onCancel}
    >
      <div
        className="w-full max-w-md rounded-lg bg-white p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-base font-semibold text-zinc-900">
          다른 라벨러 라벨 덮어쓰기
        </h3>
        <p className="mt-2 text-sm text-zinc-600">
          <span className="font-mono text-xs">{labelerShort}</span> 의 라벨을{' '}
          <span className="font-semibold">'{newDisplay}'</span> 로 덮어씁니다.
          (해당 라벨러 본인 라벨로)
        </p>
        <div className="mt-3 rounded-md bg-zinc-50 p-3 text-xs text-zinc-600 ring-1 ring-zinc-200">
          <div>이전: {oldDisplay}</div>
          <div>이후: {newDisplay}</div>
          {formNote && <div>메모: "{formNote}"</div>}
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={onCancel} disabled={saving}>
            취소
          </Button>
          <Button size="sm" onClick={onConfirm} disabled={saving || !formAction}>
            {saving ? '저장 중…' : '덮어쓰기 확인'}
          </Button>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────
// Delete confirm 모달 — owner 가 클립 영구 삭제 (R2 + DB row)
// ─────────────────────────────────────────────────────────────────
//
// 왜 별도 컴포넌트?
// - OverrideConfirmModal 과 동일 패턴, 한 파일 안에서 일관성 유지.
// - 본문 props 가 다름 (clipShortId 만 — 이전/이후 비교 없음).
//
// 동작:
// - bg-black/40 overlay 클릭 → onCancel (단, deleting 중이면 layout 의 onCancel 가 막음).
// - 카드 내부 클릭은 stopPropagation 으로 cancel 안 트리거.
// - 확인 버튼은 'danger' variant (빨강) — 파괴 작업 시그널.

function DeleteConfirmModal({
  clipShortId,
  deleting,
  onCancel,
  onConfirm,
}: {
  clipShortId: string;
  deleting: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-black/40 px-4"
      onClick={onCancel}
    >
      <div
        className="w-full max-w-md rounded-lg bg-white p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-base font-semibold text-zinc-900">클립 영구 삭제</h3>
        <p className="mt-2 text-sm text-zinc-600">
          클립{' '}
          <span className="font-mono text-xs text-zinc-900">{clipShortId}</span>{' '}
          을(를) 영구 삭제합니다. 되돌릴 수 없습니다.
        </p>
        <ul className="mt-3 list-inside list-disc rounded-md bg-zinc-50 p-3 text-xs text-zinc-600 ring-1 ring-zinc-200">
          <li>R2 영상 + 썸네일</li>
          <li>모든 라벨러의 라벨 (behavior_labels)</li>
          <li>VLM 추론 결과 + 옛 라벨 (behavior_logs)</li>
          <li>클립 row (camera_clips)</li>
        </ul>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={onCancel} disabled={deleting}>
            취소
          </Button>
          <Button variant="danger" size="sm" onClick={onConfirm} disabled={deleting}>
            {deleting ? '삭제 중…' : '영구 삭제'}
          </Button>
        </div>
      </div>
    </div>
  );
}
