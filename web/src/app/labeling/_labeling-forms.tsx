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
  VLM_ERROR_TAGS,
  allowedTargetsFor,
  type ActionSegment,
  type ContextTag,
  type GroundTruthField,
  type GroundTruthInput,
  type GroundTruthValidationIssue,
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

// 값 계약은 비-null 유지(설계 §6.1)하되 observed/segments 는 비워 프리셀렉트를 없앤다.
// visibility/primary_action 의 placeholder 값은 explicitlySelected 로 화면에서 가린다.
export function emptyGt(_duration: number): GroundTruthInput {
  return {
    visibility: 'visible', primary_action: 'moving', observed_actions: [],
    segments: [], target: 'none',
    human_confidence: 'certain', context_tags: [], activity_intensity: 'medium',
    enrichment_object: 'none', interaction_types: [], note: null,
  };
}

// 저장된 GT 를 다시 열 때는 모든 필드가 이미 "직접 선택"된 것으로 본다.
export function allSelectedFields(): Set<GroundTruthField> {
  return new Set<GroundTruthField>([
    'visibility', 'primary_action', 'observed_actions', 'segments', 'target',
    'human_confidence', 'context_tags', 'activity_intensity', 'enrichment_object',
    'interaction_types',
  ]);
}

// 첫 오류로 스크롤할 때 쓰는 섹션 anchor id.
export function fieldAnchorId(field: GroundTruthField): string {
  return `gt-field-${field}`;
}

// 대표 행동별 한 줄 도움말(설계 §5.3).
const PRIMARY_HELP: Partial<Record<PrimaryAction, string>> = {
  moving: '위치 이동·등반·자세 변경. 물체 옆을 지나가기만 해도 이동이야.',
  drinking: '물·물그릇·표면의 물에 입이 실제로 닿아 반복해서 핥는 장면.',
  hand_feeding: '사람의 손/도구가 먹이를 게코 입으로 직접 전달하는 장면.',
  shedding: '허물이 실제로 벗겨지는 장면.',
  eating_paste: '페이스트를 핥아 먹는 장면.',
  eating_prey: '먹이(곤충 등)를 사냥하거나 삼키는 장면.',
};

function issuesForField(
  issues: readonly GroundTruthValidationIssue[],
  field: GroundTruthField,
): GroundTruthValidationIssue[] {
  return issues.filter((issue) => issue.field === field);
}

function FieldError({ issues, field }: { issues: readonly GroundTruthValidationIssue[]; field: GroundTruthField }) {
  const errs = issuesForField(issues, field);
  if (errs.length === 0) return null;
  return (
    <ul className="mt-1.5 space-y-0.5 text-xs font-medium text-red-600" role="alert">
      {errs.map((e) => <li key={e.code}>⚠ {e.message}</li>)}
    </ul>
  );
}

function ChecklistItem({ done, children }: { done: boolean; children: ReactNode }) {
  return (
    <li className={done ? 'text-emerald-700' : 'text-amber-900'}>
      <span aria-hidden className="mr-1">{done ? '✓' : '○'}</span>{children}
    </li>
  );
}

// 대표 행동이 좁히는 대상만 노출하되, 현재 값이 허용 밖이면(예: drinking+none)
// 그 값을 경고 라벨로 함께 보여줘 native select 가 빈 값으로 튀지 않게 한다(설계 §5.5).
function targetOptions(current: Target, allowed: readonly Target[]): string[][] {
  const opts: string[][] = [];
  if (!allowed.includes(current)) {
    opts.push([current, `⚠ ${TARGET_LABELS[current]} — 이 대표 행동엔 안 맞아`]);
  }
  for (const target of allowed) opts.push([target, TARGET_LABELS[target]]);
  return opts;
}

export function GroundTruthForm({ gt, duration, saving, explicitlySelected, issues, patchGt, toggleObserved, updateSegment, onSave, saveLabel }: {
  gt: GroundTruthInput; duration: number; saving: boolean;
  explicitlySelected: ReadonlySet<GroundTruthField>;
  issues: readonly GroundTruthValidationIssue[];
  patchGt: <K extends keyof GroundTruthInput>(key: K, value: GroundTruthInput[K]) => void;
  toggleObserved: (action: ObservedAction) => void;
  updateSegment: (action: ObservedAction, key: 'start_sec' | 'end_sec', value: number) => void;
  onSave: () => void;
  saveLabel?: string;
}) {
  const visibilityChosen = explicitlySelected.has('visibility');
  const primaryChosen = explicitlySelected.has('primary_action');
  const isAbsent = visibilityChosen && gt.visibility === 'absent';
  const interaction = gt.observed_actions.some((a) => a.endsWith('_interaction'));
  const allowedTargets = allowedTargetsFor(gt.primary_action);
  return <Card className="space-y-5">
    <div id={fieldAnchorId('visibility')}><CardTitle>1. 게코가 보이나?</CardTitle><ChoiceRow values={['visible', 'partial', 'absent', 'uncertain']}
      labels={{ visible: '잘 보임', partial: '일부 보임', absent: '안 보임', uncertain: '불확실' }}
      selected={visibilityChosen ? gt.visibility : ''} onSelect={(v) => {
        const visibility = v as GroundTruthInput['visibility'];
        patchGt('visibility', visibility);
        if (visibility === 'absent') {
          patchGt('primary_action', 'unseen'); patchGt('observed_actions', []); patchGt('segments', []);
          patchGt('target', 'none'); patchGt('enrichment_object', 'none'); patchGt('interaction_types', []);
        }
      }} /><FieldError issues={issues} field="visibility" /></div>
    <div id={fieldAnchorId('primary_action')}><CardTitle>2. 대표 행동 하나</CardTitle>
      <p className="mt-1 text-xs text-zinc-500">영상 전체에서 가장 대표적인 의미 행동 하나야. 실제로 본 세부 동작은 아래 3번에 따로 기록해. 숫자 1–0 단축키를 쓸 수 있어.</p>
      <div className="mt-2 grid grid-cols-2 gap-2">{PRIMARY_ACTIONS.map((action) =>
        <Choice key={action} active={primaryChosen && gt.primary_action === action} onClick={() => patchGt('primary_action', action)}>
          {ACTION_LABELS[action]}{action === 'shedding' && <small className="block text-[10px] opacity-70">허물이 실제로 벗겨짐</small>}
        </Choice>)}</div>
      {primaryChosen && PRIMARY_HELP[gt.primary_action] && <p className="mt-2 rounded-md bg-zinc-100 px-3 py-2 text-xs text-zinc-600">{PRIMARY_HELP[gt.primary_action]}</p>}
      <FieldError issues={issues} field="primary_action" />
    </div>
    {gt.primary_action === 'hand_feeding' && primaryChosen && <div className="rounded-lg bg-amber-50 p-4 ring-1 ring-amber-200">
      <CardTitle>사람 급여의 객관 근거</CardTitle>
      <p className="mt-1 text-xs text-amber-800">손/도구의 존재만으로 정하지 않아. 먹이가 입으로 직접 전달되는 장면이어야 해.</p>
      <ul className="mt-2 space-y-1 text-xs">
        <ChecklistItem done={gt.observed_actions.some((a) => a === 'licking' || a === 'prey_capture')}>실제 세부 동작(3번): 핥기 또는 먹이 포획</ChecklistItem>
        <ChecklistItem done={gt.target === 'hand' || gt.target === 'tool'}>대표 행동 대상: 손 또는 도구</ChecklistItem>
        <ChecklistItem done={gt.context_tags.includes('human')}>촬영 환경 근거: 사람 등장 태그</ChecklistItem>
      </ul>
    </div>}
    {isAbsent ? (
      <div className="rounded-lg bg-zinc-100 p-4 text-sm text-zinc-600">
        <p><strong>안 보임</strong> → 대표 행동이 <strong>안 보임(unseen)</strong>으로 자동 선택됐어.</p>
        <p className="mt-1 text-xs">세부 동작·행동 구간·대표 행동 대상·활동 강도·놀이 근거는 <strong>해당 없음</strong>이야.</p>
      </div>
    ) : (
      <>
        <div id={fieldAnchorId('observed_actions')}><CardTitle>3. 게코가 실제로 한 세부 동작과 구간</CardTitle>
          <p className="mt-1 text-xs text-zinc-500">대표 행동을 다시 고르는 곳이 아니라, 화면에서 실제로 본 동작을 모두 기록하는 곳이야.</p>
          <div className="mt-2 flex flex-wrap gap-2">{OBSERVED_ACTIONS.map((action) =>
            <Choice key={action} active={gt.observed_actions.includes(action)} onClick={() => toggleObserved(action)}>{OBSERVED_LABELS[action]}</Choice>)}</div>
          <FieldError issues={issues} field="observed_actions" />
          <div id={fieldAnchorId('segments')} className="mt-3 space-y-2">{gt.segments.map((segment) =>
            <SegmentRow key={segment.action} segment={segment} duration={duration} onChange={updateSegment} />)}
            <FieldError issues={issues} field="segments" /></div>
        </div>
        <div id={fieldAnchorId('target')}><CardTitle>대표 행동 대상</CardTitle>
          <p className="mt-1 text-xs text-zinc-500">{gt.primary_action === 'drinking'
            ? '물 마시기 대상은 물·물그릇·유리/벽·바닥·불확실 중에서 골라. 쳇바퀴는 대상이 아니라 아래 놀이 근거에 기록해.'
            : gt.primary_action === 'hand_feeding'
              ? '사람 급여 대상은 손 또는 도구야.'
              : '대표 행동이 향한 대상이야. wheel 같은 놀이 상호작용 대상은 여기가 아니라 아래 놀이 근거에 기록해.'}</p>
          <select value={gt.target} onChange={(e) => patchGt('target', e.target.value as Target)}
            className="mt-2 w-full rounded-lg border border-zinc-300 bg-white p-2.5 text-sm font-normal">
            {targetOptions(gt.target, allowedTargets).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
          <FieldError issues={issues} field="target" />
        </div>
      </>
    )}
    <div className="grid gap-4 sm:grid-cols-2">
      <SelectField label="사람 확신도" value={gt.human_confidence}
        onChange={(v) => patchGt('human_confidence', v as GroundTruthInput['human_confidence'])}
        options={[["certain","확실"],["likely","가능성 높음"],["uncertain","불확실"],["unjudgeable","판단 불가"]]} />
      {!isAbsent && <div id={fieldAnchorId('activity_intensity')}><SelectField label="활동 강도" value={gt.activity_intensity}
        onChange={(v) => patchGt('activity_intensity', v as GroundTruthInput['activity_intensity'])}
        options={[["low","낮음"],["medium","보통"],["high","높음"]]} /></div>}
    </div>
    <div id={fieldAnchorId('context_tags')}><CardTitle>촬영 환경 태그</CardTitle><div className="mt-2 flex flex-wrap gap-2">{CONTEXT_TAGS.map((tag) =>
      <Choice key={tag} active={gt.context_tags.includes(tag)} onClick={() => patchGt('context_tags',
        gt.context_tags.includes(tag) ? gt.context_tags.filter((x) => x !== tag) : [...gt.context_tags, tag])}>{CONTEXT_LABELS[tag]}</Choice>)}</div>
      <FieldError issues={issues} field="context_tags" /></div>
    {!isAbsent && interaction && <div id={fieldAnchorId('enrichment_object')} className="rounded-lg bg-violet-50 p-4 ring-1 ring-violet-200">
      <CardTitle>놀이 파생용 객관 근거</CardTitle><p className="mt-1 text-xs text-violet-700">이 값은 <strong>대표 행동 대상과 별개</strong>야. ‘playing’을 추측하지 않고 무엇과 어떻게 상호작용했는지만 기록해.</p>
      <div className="mt-3"><ChoiceRow values={['wheel','toy','other','uncertain']} labels={{wheel:'쳇바퀴',toy:'장난감',other:'기타 사물',uncertain:'불확실'}}
        selected={gt.enrichment_object === 'none' ? '' : gt.enrichment_object} onSelect={(v) => patchGt('enrichment_object', v as GroundTruthInput['enrichment_object'])} /></div>
      <FieldError issues={issues} field="enrichment_object" />
      <div className="mt-3 flex flex-wrap gap-2">{INTERACTION_TYPES.map((type) =>
        <Choice key={type} active={gt.interaction_types.includes(type)} onClick={() => patchGt('interaction_types',
          gt.interaction_types.includes(type) ? gt.interaction_types.filter((x) => x !== type) : [...gt.interaction_types, type])}>{INTERACTION_LABELS[type]}</Choice>)}</div>
      <FieldError issues={issues} field="interaction_types" />
    </div>}
    <label className="block text-sm font-medium">메모 (선택)<textarea value={gt.note ?? ''}
      onChange={(e) => patchGt('note', e.target.value || null)} maxLength={2000}
      className="mt-2 min-h-20 w-full rounded-lg border border-zinc-300 p-3 font-normal outline-none focus:border-zinc-900" /></label>
    <div className="rounded-lg bg-amber-50 p-3 text-xs text-amber-900">저장하면 최초 GT는 잠겨. 이 버튼을 누르기 전까지 VLM 답은 서버에서도 공개하지 않아.</div>
    <Button size="lg" className="w-full" disabled={saving} onClick={onSave}>{saving ? '저장 중…' : (saveLabel ?? 'GT 잠그고 VLM 확인 (⌥↵)')}</Button>
  </Card>;
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
    <div><CardTitle>판정 품질</CardTitle>
      <p className="mt-1 text-xs text-zinc-500">VLM 이 실제 출력한 축(대표 action)만 평가해. 예를 들어 drinking+wheel 영상에서 VLM 이 drinking 만 냈어도, wheel 을 안 냈다는 이유만으로 부분 정답으로 내리지 마.</p>
      <ChoiceRow values={['correct','partially_correct','incorrect','unjudgeable']}
      labels={{correct:'정답',partially_correct:'부분 정답',incorrect:'오답',unjudgeable:'비교 불가'}}
      selected={review.verdict} onSelect={(v) => setReview({...review, verdict:v as VlmVerdict})} /></div>
    {(review.verdict === 'incorrect' || review.verdict === 'partially_correct') && <div>
      <CardTitle>오류 원인 (하나 이상)</CardTitle>
      <p className="mt-1 text-xs text-zinc-500">‘복수 행동 누락’은 모델이 복수 행동을 출력하는 계약일 때만 골라. 지금 스냅샷은 대표 action 하나만 낸다.</p>
      <div className="mt-2 flex flex-wrap gap-2">{VLM_ERROR_TAGS.map((tag) =>
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
