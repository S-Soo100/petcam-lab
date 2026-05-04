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
      setOverrideTarget(null);
      // 페이지 갱신 — 다른 라벨러 row 가 새 값으로 보여야.
      await load();
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
                <Badge tone="info">VLM 추론</Badge>
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
