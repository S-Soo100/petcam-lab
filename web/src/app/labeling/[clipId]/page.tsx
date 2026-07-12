'use client';

// 유저 체험 흐름:
// [영상+GT 폼] 사람이 AI 답을 모른 채 관찰 근거를 기록한다.
// → [GT 잠금] 최초 답은 바뀌지 않고 VLM 원문이 처음 공개된다.
// → [VLM 검수] 정답/부분정답/오답과 오류 원인을 남긴다.
// → [완료] 다음 미라벨 영상으로 이어진다.

import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import Badge from '@/components/ui/Badge';
import Button from '@/components/ui/Button';
import { Card, CardTitle } from '@/components/ui/Card';
import { useToast } from '@/components/Toast';
import {
  ApiError,
  UnauthorizedError,
  getClipFileUrl,
  getLabelingV2,
  getMyLabels,
  getQueue,
  saveGroundTruth,
  saveVlmReview,
  type ClipRow,
  type LabelOut,
} from '@/lib/labelingApi';
import {
  CONTEXT_TAGS,
  INTERACTION_TYPES,
  OBSERVED_ACTIONS,
  PRIMARY_ACTIONS,
  TARGETS,
  VLM_ERROR_TAGS,
  type ActionSegment,
  type ContextTag,
  type GroundTruthInput,
  type InteractionType,
  type LabelingSession,
  type ObservedAction,
  type PrimaryAction,
  type Target,
  type VlmErrorTag,
  type VlmReviewInput,
  type VlmVerdict,
} from '@/lib/labelingV2';
import { useIsOwner } from '../_owner-context';

const ACTION_LABELS: Record<PrimaryAction, string> = {
  eating_paste: '페이스트 먹기', drinking: '물 마시기', moving: '일반 이동',
  unknown: '판단 불가', eating_prey: '먹이 사냥/섭취', defecating: '배변',
  shedding: '탈피', basking: '휴식/바스킹', unseen: '안 보임', hand_feeding: '사람 급여',
};
const OBSERVED_LABELS: Record<ObservedAction, string> = {
  moving: '위치 이동', static: '정지/휴식', licking: '핥기', prey_capture: '먹이 포획',
  defecating: '배변 동작', shed_removal: '허물 벗기', wheel_interaction: '쳇바퀴 상호작용',
  object_interaction: '사물 상호작용',
};
const TARGET_LABELS: Record<Target, string> = {
  water: '물', water_bowl: '물그릇', food_bowl: '먹이그릇', paste: '페이스트', prey: '먹이',
  glass: '유리/벽', floor: '바닥', hand: '손', tool: '도구', object: '사물', none: '대상 없음',
  uncertain: '불확실',
};
const CONTEXT_LABELS: Record<ContextTag, string> = {
  ir: '야간 IR', glare: '반사광', occlusion: '가림', distant: '멀리 있음', blur: '흐림',
  overexposure: '과노출', edge: '화면 가장자리', human: '사람 등장', shadow: '그림자',
  camera_motion: '카메라 흔들림', empty_scene: '빈 장면',
};
const INTERACTION_LABELS: Record<InteractionType, string> = {
  ride: '올라타기', push: '밀기', rotate: '회전시키기', chase: '쫓기',
  repeated_return: '반복해서 돌아오기', other: '기타',
};
const ERROR_LABELS: Record<VlmErrorTag, string> = {
  action_confusion: '행동 혼동', target_confusion: '대상 혼동', gecko_missed: '게코 놓침',
  morph_confusion: '신체/허물 혼동', ir_or_glare: 'IR·반사 오인', timing_error: '구간 오류',
  insufficient_evidence: '근거 부족', multi_action_missed: '복수 행동 누락',
};

function emptyGt(duration: number): GroundTruthInput {
  return {
    visibility: 'visible', primary_action: 'moving', observed_actions: ['moving'],
    segments: [{ action: 'moving', start_sec: 0, end_sec: duration }], target: 'none',
    human_confidence: 'certain', context_tags: [], activity_intensity: 'medium',
    enrichment_object: 'none', interaction_types: [], note: null,
  };
}

export default function LabelClipPage() {
  const router = useRouter();
  const { clipId } = useParams<{ clipId: string }>();
  const toast = useToast();
  const isOwner = useIsOwner();
  const [clip, setClip] = useState<ClipRow | null>(null);
  const [session, setSession] = useState<LabelingSession | null>(null);
  const [metadata, setMetadata] = useState<Record<string, unknown>>({});
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [playbackRate, setPlaybackRate] = useState(1);
  const [compatLabels, setCompatLabels] = useState<LabelOut[]>([]);
  const [gt, setGt] = useState<GroundTruthInput>(() => emptyGt(60));
  const [review, setReview] = useState<VlmReviewInput>({ verdict: 'correct', error_tags: [], note: null });
  const [busy, setBusy] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const duration = useMemo(() => Number(clip?.duration_sec) || 60, [clip]);
  const prediction = session?.prediction_snapshot ?? null;
  const gtLocked = Boolean(session?.initial_gt);
  const completed = session?.stage === 'completed';

  const load = useCallback(async () => {
    setBusy(true); setError(null);
    try {
      const [state, playback] = await Promise.all([
        getLabelingV2(clipId), getClipFileUrl(clipId),
      ]);
      setClip(state.clip); setSession(state.session); setMetadata(state.system_metadata);
      setVideoUrl(playback.url);
      const saved = state.session?.current_gt ?? state.session?.initial_gt;
      setGt(saved ?? emptyGt(Number(state.clip.duration_sec) || 60));
      if (state.session?.vlm_verdict) {
        setReview({ verdict: state.session.vlm_verdict, error_tags: state.session.vlm_error_tags,
          note: state.session.vlm_review_note });
      }
    } catch (cause) {
      if (cause instanceof UnauthorizedError) { router.replace('/labeling/login'); return; }
      setError(cause instanceof ApiError ? cause.message : (cause as Error).message);
    } finally { setBusy(false); }
  }, [clipId, router]);

  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    if (!gtLocked) return;
    getMyLabels(clipId).then(setCompatLabels).catch(() => setCompatLabels([]));
  }, [clipId, gtLocked]);

  useEffect(() => {
    if (gtLocked) return;
    const onKeyDown = (event: KeyboardEvent) => {
      const tag = (event.target as HTMLElement | null)?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
      const index = Number(event.key) - 1;
      if (index >= 0 && index < PRIMARY_ACTIONS.length) {
        event.preventDefault(); patchGt('primary_action', PRIMARY_ACTIONS[index]);
      }
      if (event.altKey && event.key === 'Enter' && !saving) {
        event.preventDefault(); void lockGt();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  });

  function patchGt<K extends keyof GroundTruthInput>(key: K, value: GroundTruthInput[K]) {
    setGt((current) => ({ ...current, [key]: value }));
  }
  function toggleObserved(action: ObservedAction) {
    const enabled = gt.observed_actions.includes(action);
    const nextObserved = enabled
      ? gt.observed_actions.filter((item) => item !== action)
      : [...gt.observed_actions, action];
    patchGt('observed_actions', nextObserved);
    patchGt('segments', enabled
      ? gt.segments.filter((segment) => segment.action !== action)
      : [...gt.segments, { action, start_sec: 0, end_sec: duration }]);
    if (!nextObserved.some((item) => item.endsWith('_interaction'))) {
      patchGt('enrichment_object', 'none');
      patchGt('interaction_types', []);
    }
  }
  function updateSegment(action: ObservedAction, key: 'start_sec' | 'end_sec', value: number) {
    patchGt('segments', gt.segments.map((segment) =>
      segment.action === action ? { ...segment, [key]: value } : segment));
  }

  async function lockGt() {
    setSaving(true); setError(null);
    try {
      const result = await saveGroundTruth(clipId, gt);
      setSession(result.session);
      if (!result.requires_vlm_review) {
        toast.show('GT 저장 완료 · VLM 판정 없음', 'success');
      } else {
        toast.show('GT 잠금 완료 · 이제 VLM을 검수해', 'success');
      }
    } catch (cause) {
      const message = cause instanceof ApiError ? cause.message : (cause as Error).message;
      setError(message); toast.show(`저장 실패: ${message}`, 'error');
    } finally { setSaving(false); }
  }

  async function completeReview() {
    setSaving(true); setError(null);
    try {
      const result = await saveVlmReview(clipId, review);
      setSession(result.session); toast.show('검수 완료', 'success');
      await goNext();
    } catch (cause) {
      const message = cause instanceof ApiError ? cause.message : (cause as Error).message;
      setError(message); toast.show(`검수 실패: ${message}`, 'error');
    } finally { setSaving(false); }
  }

  async function goNext() {
    try {
      const queue = await getQueue({ limit: 1 });
      if (queue.items[0]) { router.push(`/labeling/${queue.items[0].id}`); return; }
    } catch { /* 큐 오류면 목록으로 복귀 */ }
    router.push('/labeling');
  }

  async function deleteClip() {
    if (!isOwner || !confirm('이 영상과 관련 라벨을 영구 삭제할까?')) return;
    setSaving(true);
    try {
      const { getSupabaseBrowser } = await import('@/lib/supabaseBrowser');
      const { data } = await getSupabaseBrowser().auth.getSession();
      const response = await fetch(`/api/clips/${clipId}`, {
        method: 'DELETE', headers: { Authorization: `Bearer ${data.session?.access_token ?? ''}` },
      });
      if (!response.ok) throw new Error('삭제하지 못했어.');
      router.push('/labeling');
    } catch (cause) { setError((cause as Error).message); setSaving(false); }
  }

  if (busy) return <main className="mx-auto max-w-6xl px-5 py-8 text-sm text-zinc-500">불러오는 중…</main>;

  return (
    <main className="mx-auto max-w-6xl space-y-5 px-4 py-5 sm:px-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <Link href="/labeling" className="text-xs text-zinc-500 hover:text-zinc-900">← 라벨 대기 큐</Link>
          <h1 className="mt-1 text-xl font-semibold tracking-tight">영상 근거 라벨링</h1>
          <p className="text-sm text-zinc-500">사람 GT를 먼저 잠근 뒤 같은 화면에서 VLM 판정을 검수해.</p>
        </div>
        <div className="flex items-center gap-2">
          <Badge tone={completed ? 'success' : gtLocked ? 'info' : 'warning'}>
            {completed ? '완료' : gtLocked ? '2단계 · VLM 검수' : '1단계 · Blind GT'}
          </Badge>
          {isOwner && <Button size="sm" variant="ghost" onClick={deleteClip} disabled={saving}>삭제</Button>}
        </div>
      </header>

      {error && <div className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700 ring-1 ring-red-200">{error}</div>}

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.25fr)_minmax(360px,.75fr)]">
        <section className="space-y-4 lg:sticky lg:top-5 lg:self-start">
          <Card padding="none" className="overflow-hidden bg-black">
            {videoUrl ? <video ref={videoRef} src={videoUrl} controls playsInline className="aspect-video w-full" />
              : <div className="grid aspect-video place-items-center text-sm text-zinc-400">영상을 불러오지 못했어.</div>}
          </Card>
          <div className="flex flex-wrap items-center gap-2 rounded-lg border border-zinc-200 bg-white p-2 text-xs">
            <button className="rounded border px-2 py-1" onClick={() => { if (videoRef.current) videoRef.current.currentTime = Math.max(0, videoRef.current.currentTime - 1 / 30); }}>−1 frame</button>
            <button className="rounded border px-2 py-1" onClick={() => { if (videoRef.current) videoRef.current.currentTime += 1 / 30; }}>+1 frame</button>
            <label className="ml-auto">재생 속도 <select className="ml-1 rounded border p-1" value={playbackRate} onChange={(event) => {
              const rate = Number(event.target.value); setPlaybackRate(rate); if (videoRef.current) videoRef.current.playbackRate = rate;
            }}><option value="0.25">0.25×</option><option value="0.5">0.5×</option><option value="1">1×</option><option value="1.5">1.5×</option><option value="2">2×</option></select></label>
          </div>
          <MetadataCard metadata={metadata} clipId={clipId} />
        </section>

        <section className="space-y-4">
          {!gtLocked ? (
            <GroundTruthForm gt={gt} duration={duration} saving={saving}
              patchGt={patchGt} toggleObserved={toggleObserved} updateSegment={updateSegment}
              onSave={lockGt} />
          ) : (
            <>
              <GtSummary gt={session?.initial_gt ?? gt} />
              {prediction ? (
                <VlmReviewCard prediction={prediction} humanGt={session?.initial_gt ?? gt}
                  review={review} setReview={setReview} saving={saving}
                  completed={completed} onComplete={completeReview} />
              ) : (
                <Card className="border-emerald-200 bg-emerald-50">
                  <CardTitle>GT 저장 완료</CardTitle>
                  <p className="mt-2 text-sm text-emerald-800">이 영상에는 VLM 판정이 없어 사람 GT만 저장했어.</p>
                </Card>
              )}
              {completed && <Button className="w-full" size="lg" onClick={goNext}>다음 영상</Button>}
              {compatLabels.length > 0 && <Card padding="sm"><details><summary className="cursor-pointer text-xs font-medium text-zinc-600">기존 behavior_labels 호환 기록 ({compatLabels.length})</summary>
                <ul className="mt-2 space-y-1 text-xs text-zinc-600">{compatLabels.map((label) => <li key={label.id}>{label.action} · {label.labeled_by.slice(0, 8)} · {label.note || '메모 없음'}</li>)}</ul>
              </details></Card>}
            </>
          )}
        </section>
      </div>
    </main>
  );
}

function GroundTruthForm({ gt, duration, saving, patchGt, toggleObserved, updateSegment, onSave }: {
  gt: GroundTruthInput; duration: number; saving: boolean;
  patchGt: <K extends keyof GroundTruthInput>(key: K, value: GroundTruthInput[K]) => void;
  toggleObserved: (action: ObservedAction) => void;
  updateSegment: (action: ObservedAction, key: 'start_sec' | 'end_sec', value: number) => void;
  onSave: () => void;
}) {
  const interaction = gt.observed_actions.some((a) => a.endsWith('_interaction'));
  return <Card className="space-y-5">
    <div><CardTitle>1. 게코가 보이나?</CardTitle><ChoiceRow values={['visible', 'partial', 'absent', 'uncertain']}
      labels={{ visible: '잘 보임', partial: '일부 보임', absent: '안 보임', uncertain: '불확실' }}
      selected={gt.visibility} onSelect={(v) => {
        const visibility = v as GroundTruthInput['visibility'];
        patchGt('visibility', visibility);
        if (visibility === 'absent') {
          patchGt('primary_action', 'unseen'); patchGt('observed_actions', []); patchGt('segments', []);
          patchGt('target', 'none'); patchGt('enrichment_object', 'none'); patchGt('interaction_types', []);
        }
      }} /></div>
    <div><CardTitle>2. 대표 행동 하나</CardTitle>
      <p className="mt-1 text-xs text-zinc-500">‘일반 이동’은 지나가기·등반·자세 변경이야. Wheel/Object 상호작용은 타기·밀기·회전·반복 접근으로 기록해. 빠르다는 이유만으로 놀이로 분류하지 않아. 숫자 1–0 단축키를 쓸 수 있어.</p>
      <div className="mt-2 grid grid-cols-2 gap-2">{PRIMARY_ACTIONS.map((action) =>
        <Choice key={action} active={gt.primary_action === action} onClick={() => patchGt('primary_action', action)}>
          {ACTION_LABELS[action]}{action === 'shedding' && <small className="block text-[10px] opacity-70">허물이 실제로 벗겨짐</small>}
        </Choice>)}</div>
    </div>
    <div><CardTitle>3. 관찰된 모든 행동과 구간</CardTitle>
      <div className="mt-2 flex flex-wrap gap-2">{OBSERVED_ACTIONS.map((action) =>
        <Choice key={action} active={gt.observed_actions.includes(action)} onClick={() => toggleObserved(action)}>{OBSERVED_LABELS[action]}</Choice>)}</div>
      <div className="mt-3 space-y-2">{gt.segments.map((segment) =>
        <SegmentRow key={segment.action} segment={segment} duration={duration} onChange={updateSegment} />)}</div>
    </div>
    <div className="grid gap-4 sm:grid-cols-2">
      <SelectField label="행동 대상" value={gt.target} onChange={(v) => patchGt('target', v as Target)}
        options={TARGETS.map((v) => [v, TARGET_LABELS[v]])} />
      <SelectField label="사람 확신도" value={gt.human_confidence}
        onChange={(v) => patchGt('human_confidence', v as GroundTruthInput['human_confidence'])}
        options={[["certain","확실"],["likely","가능성 높음"],["uncertain","불확실"],["unjudgeable","판단 불가"]]} />
      <SelectField label="활동 강도" value={gt.activity_intensity}
        onChange={(v) => patchGt('activity_intensity', v as GroundTruthInput['activity_intensity'])}
        options={[["low","낮음"],["medium","보통"],["high","높음"]]} />
    </div>
    <div><CardTitle>촬영 환경 태그</CardTitle><div className="mt-2 flex flex-wrap gap-2">{CONTEXT_TAGS.map((tag) =>
      <Choice key={tag} active={gt.context_tags.includes(tag)} onClick={() => patchGt('context_tags',
        gt.context_tags.includes(tag) ? gt.context_tags.filter((x) => x !== tag) : [...gt.context_tags, tag])}>{CONTEXT_LABELS[tag]}</Choice>)}</div></div>
    {interaction && <div className="rounded-lg bg-violet-50 p-4 ring-1 ring-violet-200">
      <CardTitle>놀이 파생용 객관 근거</CardTitle><p className="mt-1 text-xs text-violet-700">‘playing’을 추측하지 않아. 무엇과 어떻게 상호작용했는지만 기록해.</p>
      <div className="mt-3"><ChoiceRow values={['wheel','toy','other','uncertain']} labels={{wheel:'쳇바퀴',toy:'장난감',other:'기타 사물',uncertain:'불확실'}}
        selected={gt.enrichment_object} onSelect={(v) => patchGt('enrichment_object', v as GroundTruthInput['enrichment_object'])} /></div>
      <div className="mt-3 flex flex-wrap gap-2">{INTERACTION_TYPES.map((type) =>
        <Choice key={type} active={gt.interaction_types.includes(type)} onClick={() => patchGt('interaction_types',
          gt.interaction_types.includes(type) ? gt.interaction_types.filter((x) => x !== type) : [...gt.interaction_types, type])}>{INTERACTION_LABELS[type]}</Choice>)}</div>
    </div>}
    <label className="block text-sm font-medium">메모 (선택)<textarea value={gt.note ?? ''}
      onChange={(e) => patchGt('note', e.target.value || null)} maxLength={2000}
      className="mt-2 min-h-20 w-full rounded-lg border border-zinc-300 p-3 font-normal outline-none focus:border-zinc-900" /></label>
    <div className="rounded-lg bg-amber-50 p-3 text-xs text-amber-900">저장하면 최초 GT는 잠겨. 이 버튼을 누르기 전까지 VLM 답은 서버에서도 공개하지 않아.</div>
    <Button size="lg" className="w-full" disabled={saving} onClick={onSave}>{saving ? '저장 중…' : 'GT 잠그고 VLM 확인 (⌥↵)'}</Button>
  </Card>;
}

function VlmReviewCard({ prediction, humanGt, review, setReview, saving, completed, onComplete }: {
  prediction: Record<string, unknown>; humanGt: GroundTruthInput; review: VlmReviewInput;
  setReview: (value: VlmReviewInput) => void; saving: boolean; completed: boolean; onComplete: () => void;
}) {
  const action = String(prediction.action ?? 'unknown');
  const sheddingConfirmed = action === 'shedding' && humanGt.primary_action === 'shedding';
  return <Card className="space-y-4 border-sky-200">
    <div><Badge tone="info">GT 잠금 후 공개됨</Badge><CardTitle className="mt-2">VLM 판정 원문</CardTitle></div>
    <div className="rounded-lg bg-zinc-950 p-4 text-zinc-50">
      <div className="text-lg font-semibold">{action === 'shedding' ? (sheddingConfirmed ? '탈피 확인' : 'AI 탈피 의심 · 확인 필요') : action}</div>
      <div className="mt-1 text-xs text-zinc-400">confidence {String(prediction.confidence ?? '없음')} · {String(prediction.vlm_model ?? 'model 미기록')}</div>
      {prediction.reasoning ? <p className="mt-3 whitespace-pre-wrap text-sm text-zinc-300">{String(prediction.reasoning)}</p> : null}
      <details className="mt-3 text-xs text-zinc-400"><summary className="cursor-pointer">정확한 snapshot 전체</summary><pre className="mt-2 overflow-auto whitespace-pre-wrap">{JSON.stringify(prediction, null, 2)}</pre></details>
    </div>
    <div><CardTitle>판정 품질</CardTitle><ChoiceRow values={['correct','partially_correct','incorrect','unjudgeable']}
      labels={{correct:'정답',partially_correct:'부분 정답',incorrect:'오답',unjudgeable:'비교 불가'}}
      selected={review.verdict} onSelect={(v) => setReview({...review, verdict:v as VlmVerdict})} /></div>
    {(review.verdict === 'incorrect' || review.verdict === 'partially_correct') && <div>
      <CardTitle>오류 원인 (하나 이상)</CardTitle><div className="mt-2 flex flex-wrap gap-2">{VLM_ERROR_TAGS.map((tag) =>
        <Choice key={tag} active={review.error_tags.includes(tag)} onClick={() => setReview({...review, error_tags:
          review.error_tags.includes(tag) ? review.error_tags.filter((x) => x !== tag) : [...review.error_tags, tag]})}>{ERROR_LABELS[tag]}</Choice>)}</div></div>}
    <label className="block text-sm font-medium">검수 메모 (선택)<textarea value={review.note ?? ''}
      onChange={(e) => setReview({...review, note:e.target.value || null})} maxLength={2000}
      className="mt-2 min-h-16 w-full rounded-lg border border-zinc-300 p-3 font-normal" /></label>
    {!completed && <Button size="lg" className="w-full" disabled={saving} onClick={onComplete}>{saving ? '저장 중…' : '검수 완료하고 다음 영상'}</Button>}
  </Card>;
}

function GtSummary({ gt }: { gt: GroundTruthInput }) {
  return <Card className="border-emerald-200 bg-emerald-50"><div className="flex items-center justify-between"><CardTitle>잠긴 최초 GT</CardTitle><Badge tone="success">bias 방지 기록</Badge></div>
    <p className="mt-2 text-sm text-emerald-950"><strong>{ACTION_LABELS[gt.primary_action]}</strong> · {gt.visibility} · 활동 {gt.activity_intensity}</p>
    <p className="mt-1 text-xs text-emerald-800">{gt.observed_actions.map((a) => OBSERVED_LABELS[a]).join(' · ') || '관찰 행동 없음'}</p></Card>;
}

function MetadataCard({ metadata, clipId }: { metadata: Record<string, unknown>; clipId: string }) {
  return <Card padding="sm"><details><summary className="cursor-pointer text-sm font-medium">시스템 메타데이터</summary>
    <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-xs">{Object.entries(metadata).map(([key,value]) =>
      <div key={key}><dt className="text-zinc-500">{key}</dt><dd className="truncate font-mono">{String(value ?? '—')}</dd></div>)}</dl>
    <p className="mt-2 truncate font-mono text-[10px] text-zinc-400">{clipId}</p></details></Card>;
}

function SegmentRow({ segment, duration, onChange }: { segment: ActionSegment; duration: number;
  onChange: (action: ObservedAction, key: 'start_sec' | 'end_sec', value: number) => void }) {
  return <div className="grid grid-cols-[1fr_80px_10px_80px] items-center gap-2 rounded-lg bg-zinc-50 p-2 text-xs">
    <span>{OBSERVED_LABELS[segment.action]}</span><input type="number" min={0} max={duration} step="0.1" value={segment.start_sec}
      onChange={(e) => onChange(segment.action,'start_sec',Number(e.target.value))} className="rounded border p-1.5"/><span>–</span>
    <input type="number" min={0} max={duration} step="0.1" value={segment.end_sec}
      onChange={(e) => onChange(segment.action,'end_sec',Number(e.target.value))} className="rounded border p-1.5"/>
  </div>;
}

function Choice({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return <button type="button" aria-pressed={active} onClick={onClick}
    className={`rounded-lg border px-3 py-2 text-left text-xs font-medium transition ${active ? 'border-zinc-900 bg-zinc-900 text-white' : 'border-zinc-300 bg-white text-zinc-700 hover:border-zinc-500'}`}>{children}</button>;
}
function ChoiceRow({ values, labels, selected, onSelect }: { values: readonly string[]; labels: Record<string,string>; selected: string; onSelect: (value:string)=>void }) {
  return <div className="mt-2 flex flex-wrap gap-2">{values.map((value) => <Choice key={value} active={selected === value} onClick={() => onSelect(value)}>{labels[value]}</Choice>)}</div>;
}
function SelectField({ label, value, options, onChange }: { label:string; value:string; options:string[][]; onChange:(value:string)=>void }) {
  return <label className="text-sm font-medium">{label}<select value={value} onChange={(e)=>onChange(e.target.value)}
    className="mt-2 w-full rounded-lg border border-zinc-300 bg-white p-2.5 font-normal">{options.map(([v,l])=><option key={v} value={v}>{l}</option>)}</select></label>;
}
