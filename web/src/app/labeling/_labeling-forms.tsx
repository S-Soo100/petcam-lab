'use client';

// 라벨링 GT/VLM 폼 · 영상 플레이어 — production 상세와 튜토리얼 lesson 이 공유하는
// mode-independent 컴포넌트(설계 §18). 상태·저장 로직은 각 페이지가 소유하고 여기엔
// presentational 컴포넌트만 둔다. 저장 API 는 페이지별로 분리(production vs tutorial).

import { useRef, useState, type ReactNode } from 'react';

import Badge from '@/components/ui/Badge';
import Button from '@/components/ui/Button';
import { Card, CardTitle } from '@/components/ui/Card';
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
  type ObservedAction,
  type PrimaryAction,
  type Target,
  type VlmErrorTag,
  type VlmReviewInput,
  type VlmVerdict,
} from '@/lib/labelingV2';

export const ACTION_LABELS: Record<PrimaryAction, string> = {
  eating_paste: '페이스트 먹기', drinking: '물 마시기', moving: '일반 이동',
  unknown: '판단 불가', eating_prey: '먹이 사냥/섭취', defecating: '배변',
  shedding: '탈피', basking: '휴식/바스킹', unseen: '안 보임', hand_feeding: '사람 급여',
};
export const OBSERVED_LABELS: Record<ObservedAction, string> = {
  moving: '위치 이동', static: '정지/휴식', licking: '핥기', prey_capture: '먹이 포획',
  defecating: '배변 동작', shed_removal: '허물 벗기', wheel_interaction: '쳇바퀴 상호작용',
  object_interaction: '사물 상호작용',
};
export const TARGET_LABELS: Record<Target, string> = {
  water: '물', water_bowl: '물그릇', food_bowl: '먹이그릇', paste: '페이스트', prey: '먹이',
  glass: '유리/벽', floor: '바닥', hand: '손', tool: '도구', object: '사물', none: '대상 없음',
  uncertain: '불확실',
};
export const CONTEXT_LABELS: Record<ContextTag, string> = {
  ir: '야간 IR', glare: '반사광', occlusion: '가림', distant: '멀리 있음', blur: '흐림',
  overexposure: '과노출', edge: '화면 가장자리', human: '사람 등장', shadow: '그림자',
  camera_motion: '카메라 흔들림', empty_scene: '빈 장면',
};
export const INTERACTION_LABELS: Record<InteractionType, string> = {
  ride: '올라타기', push: '밀기', rotate: '회전시키기', chase: '쫓기',
  repeated_return: '반복해서 돌아오기', other: '기타',
};
export const ERROR_LABELS: Record<VlmErrorTag, string> = {
  action_confusion: '행동 혼동', target_confusion: '대상 혼동', gecko_missed: '게코 놓침',
  morph_confusion: '신체/허물 혼동', ir_or_glare: 'IR·반사 오인', timing_error: '구간 오류',
  insufficient_evidence: '근거 부족', multi_action_missed: '복수 행동 누락',
};

export function emptyGt(duration: number): GroundTruthInput {
  return {
    visibility: 'visible', primary_action: 'moving', observed_actions: ['moving'],
    segments: [{ action: 'moving', start_sec: 0, end_sec: duration }], target: 'none',
    human_confidence: 'certain', context_tags: [], activity_intensity: 'medium',
    enrichment_object: 'none', interaction_types: [], note: null,
  };
}

// 영상 + frame step + 속도 제어. ref·playbackRate 를 내부에서 관리한다.
export function VideoPlayer({ src }: { src: string | null }) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [playbackRate, setPlaybackRate] = useState(1);
  return (
    <>
      <Card padding="none" className="overflow-hidden bg-black">
        {src ? <video ref={videoRef} src={src} controls playsInline className="aspect-video w-full" />
          : <div className="grid aspect-video place-items-center text-sm text-zinc-400">영상을 불러오지 못했어.</div>}
      </Card>
      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-zinc-200 bg-white p-2 text-xs">
        <button className="rounded border px-2 py-1" onClick={() => { if (videoRef.current) videoRef.current.currentTime = Math.max(0, videoRef.current.currentTime - 1 / 30); }}>−1 frame</button>
        <button className="rounded border px-2 py-1" onClick={() => { if (videoRef.current) videoRef.current.currentTime += 1 / 30; }}>+1 frame</button>
        <label className="ml-auto">재생 속도 <select className="ml-1 rounded border p-1" value={playbackRate} onChange={(event) => {
          const rate = Number(event.target.value); setPlaybackRate(rate); if (videoRef.current) videoRef.current.playbackRate = rate;
        }}><option value="0.25">0.25×</option><option value="0.5">0.5×</option><option value="1">1×</option><option value="1.5">1.5×</option><option value="2">2×</option></select></label>
      </div>
    </>
  );
}

export function GroundTruthForm({ gt, duration, saving, patchGt, toggleObserved, updateSegment, onSave, saveLabel }: {
  gt: GroundTruthInput; duration: number; saving: boolean;
  patchGt: <K extends keyof GroundTruthInput>(key: K, value: GroundTruthInput[K]) => void;
  toggleObserved: (action: ObservedAction) => void;
  updateSegment: (action: ObservedAction, key: 'start_sec' | 'end_sec', value: number) => void;
  onSave: () => void;
  saveLabel?: string;
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
    <Button size="lg" className="w-full" disabled={saving} onClick={onSave}>{saving ? '저장 중…' : (saveLabel ?? 'GT 잠그고 VLM 확인 (⌥↵)')}</Button>
  </Card>;
}

export function VlmReviewCard({ prediction, humanGt, review, setReview, saving, completed, onComplete, completeLabel }: {
  prediction: Record<string, unknown>; humanGt: GroundTruthInput; review: VlmReviewInput;
  setReview: (value: VlmReviewInput) => void; saving: boolean; completed: boolean; onComplete: () => void;
  completeLabel?: string;
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
    {!completed && <Button size="lg" className="w-full" disabled={saving} onClick={onComplete}>{saving ? '저장 중…' : (completeLabel ?? '검수 완료하고 다음 영상')}</Button>}
  </Card>;
}

export function GtSummary({ gt }: { gt: GroundTruthInput }) {
  return <Card className="border-emerald-200 bg-emerald-50"><div className="flex items-center justify-between"><CardTitle>잠긴 최초 GT</CardTitle><Badge tone="success">bias 방지 기록</Badge></div>
    <p className="mt-2 text-sm text-emerald-950"><strong>{ACTION_LABELS[gt.primary_action]}</strong> · {gt.visibility} · 활동 {gt.activity_intensity}</p>
    <p className="mt-1 text-xs text-emerald-800">{gt.observed_actions.map((a) => OBSERVED_LABELS[a]).join(' · ') || '관찰 행동 없음'}</p></Card>;
}

export function MetadataCard({ metadata, clipId }: { metadata: Record<string, unknown>; clipId: string }) {
  return <Card padding="sm"><details><summary className="cursor-pointer text-sm font-medium">시스템 메타데이터</summary>
    <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-xs">{Object.entries(metadata).map(([key,value]) =>
      <div key={key}><dt className="text-zinc-500">{key}</dt><dd className="truncate font-mono">{String(value ?? '—')}</dd></div>)}</dl>
    <p className="mt-2 truncate font-mono text-[10px] text-zinc-400">{clipId}</p></details></Card>;
}

export function SegmentRow({ segment, duration, onChange }: { segment: ActionSegment; duration: number;
  onChange: (action: ObservedAction, key: 'start_sec' | 'end_sec', value: number) => void }) {
  return <div className="grid grid-cols-[1fr_80px_10px_80px] items-center gap-2 rounded-lg bg-zinc-50 p-2 text-xs">
    <span>{OBSERVED_LABELS[segment.action]}</span><input type="number" min={0} max={duration} step="0.1" value={segment.start_sec}
      onChange={(e) => onChange(segment.action,'start_sec',Number(e.target.value))} className="rounded border p-1.5"/><span>–</span>
    <input type="number" min={0} max={duration} step="0.1" value={segment.end_sec}
      onChange={(e) => onChange(segment.action,'end_sec',Number(e.target.value))} className="rounded border p-1.5"/>
  </div>;
}

export function Choice({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) {
  return <button type="button" aria-pressed={active} onClick={onClick}
    className={`rounded-lg border px-3 py-2 text-left text-xs font-medium transition ${active ? 'border-zinc-900 bg-zinc-900 text-white' : 'border-zinc-300 bg-white text-zinc-700 hover:border-zinc-500'}`}>{children}</button>;
}
export function ChoiceRow({ values, labels, selected, onSelect }: { values: readonly string[]; labels: Record<string,string>; selected: string; onSelect: (value:string)=>void }) {
  return <div className="mt-2 flex flex-wrap gap-2">{values.map((value) => <Choice key={value} active={selected === value} onClick={() => onSelect(value)}>{labels[value]}</Choice>)}</div>;
}
export function SelectField({ label, value, options, onChange }: { label:string; value:string; options:string[][]; onChange:(value:string)=>void }) {
  return <label className="text-sm font-medium">{label}<select value={value} onChange={(e)=>onChange(e.target.value)}
    className="mt-2 w-full rounded-lg border border-zinc-300 bg-white p-2.5 font-normal">{options.map(([v,l])=><option key={v} value={v}>{l}</option>)}</select></label>;
}
