'use client';

// 라벨링 GT/VLM 폼 · 영상 플레이어 — production 상세와 튜토리얼 lesson 이 공유하는
// mode-independent 컴포넌트. 상태·저장 로직은 각 페이지가 소유하고 여기엔 presentational
// 컴포넌트만 둔다. 저장 API 는 페이지별로 분리(production vs tutorial).
//
// 화면 문구·enum 한국어 표시는 전부 공통 표시 계층(@/lib/labelingDisplay)에서 가져온다(설계 §7).
// 라벨러 화면에 GT/Blind GT/VLM/wheel/target/enrichment/action 같은 내부 용어를 노출하지 않는다.

import { useRef, useState, type ReactNode } from 'react';

import Badge from '@/components/ui/Badge';
import Button from '@/components/ui/Button';
import { Card, CardTitle } from '@/components/ui/Card';
import {
  CONTEXT_TAGS,
  HIGHLIGHT_RECOMMENDATIONS,
  INTERACTION_TYPES,
  OBSERVED_ACTIONS,
  PRIMARY_ACTIONS,
  VLM_ERROR_TAGS,
  allowedTargetsFor,
  type ActionSegment,
  type GroundTruthField,
  type GroundTruthInput,
  type GroundTruthValidationIssue,
  type HighlightRecommendation,
  type ObservedAction,
  type Target,
  type Visibility,
  type VlmReviewInput,
  type VlmVerdict,
} from '@/lib/labelingV2';
import {
  ACTION_LABELS,
  CONFIDENCE_LABELS,
  CONTEXT_LABELS,
  CONTEXT_TAGS_HELP,
  CONTEXT_TAGS_NONE_LABEL,
  CONTEXT_TAGS_TITLE,
  ENRICHMENT_LABELS,
  ERROR_LABELS,
  HIGHLIGHT_LABELS,
  INTERACTION_LABELS,
  OBSERVED_LABELS,
  PRIMARY_HELP,
  TARGET_LABELS,
  TARGET_PROMPT_COMMON_NOTE,
  TARGET_TOOL_OBJECT_NOTE,
  UNKNOWN_LABEL,
  VERDICT_HELP,
  VERDICT_LABELS,
  VISIBILITY_LABELS,
  describeSegment,
  formatActionLabel,
  formatVideoEndLabel,
  highlightSummaryClause,
  isVideoEnd,
  targetPromptFor,
} from '@/lib/labelingDisplay';

const VERDICT_ORDER = ['correct', 'partially_correct', 'incorrect', 'unjudgeable'] as const;

// 값 계약은 비-null 유지(설계 §6.1)하되 observed/segments 는 비워 프리셀렉트를 없앤다.
// visibility/primary_action/highlight 의 placeholder 값은 explicitlySelected 로 화면에서 가린다.
// activity_intensity 는 신규 GT 에서 null(legacy read 전용, §6.3).
export function emptyGt(_duration: number): GroundTruthInput {
  return {
    visibility: 'visible', primary_action: 'moving', observed_actions: [],
    segments: [], target: 'none',
    human_confidence: 'certain', context_tags: [], activity_intensity: null,
    highlight_recommendation: 'include',
    enrichment_object: 'none', interaction_types: [], note: null,
  };
}

// 저장된 GT 를 다시 열 때는 모든 필드가 이미 "직접 선택"된 것으로 본다.
export function allSelectedFields(): Set<GroundTruthField> {
  return new Set<GroundTruthField>([
    'visibility', 'primary_action', 'observed_actions', 'segments', 'target',
    'human_confidence', 'context_tags', 'highlight_recommendation', 'enrichment_object',
    'interaction_types',
  ]);
}

// 세부 동작을 새로 켤 때 만드는 기본 구간(영상 전체). 끝 시각은 실제 clip duration 을 그대로
// 저장한다 — 반올림(31.7999→31.8)하면 서버 검증(end_sec<=duration)을 넘고 저장 정밀도가 깨진다(하드닝 §2).
// 화면 표시만 소수 첫째 자리로 반올림하고, 저장값은 원본을 유지한다.
export function freshSegment(action: ObservedAction, duration: number): ActionSegment {
  return { action, start_sec: 0, end_sec: duration };
}

// 첫 오류로 스크롤할 때 쓰는 섹션 anchor id.
export function fieldAnchorId(field: GroundTruthField): string {
  return `gt-field-${field}`;
}

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
// 그 값을 경고 라벨로 함께 보여줘 native select 가 빈 값으로 튀지 않게 한다(설계 §5.3).
function targetOptions(current: Target, allowed: readonly Target[]): string[][] {
  const opts: string[][] = [];
  if (!allowed.includes(current)) {
    opts.push([current, `⚠ ${TARGET_LABELS[current]} — 이 대표 행동엔 안 맞아`]);
  }
  for (const target of allowed) opts.push([target, TARGET_LABELS[target]]);
  return opts;
}

export function GroundTruthForm({ gt, duration, saving, explicitlySelected, issues, patchGt, onSelectVisibility, toggleObserved, updateSegment, onSave, saveLabel }: {
  gt: GroundTruthInput; duration: number; saving: boolean;
  explicitlySelected: ReadonlySet<GroundTruthField>;
  issues: readonly GroundTruthValidationIssue[];
  patchGt: <K extends keyof GroundTruthInput>(key: K, value: GroundTruthInput[K]) => void;
  // 가시성 변경은 absent 정규화 + highlight 직접선택 해제를 함께 처리한다(하드닝 §6). 페이지가 소유.
  onSelectVisibility: (visibility: Visibility) => void;
  toggleObserved: (action: ObservedAction) => void;
  updateSegment: (action: ObservedAction, key: 'start_sec' | 'end_sec', value: number) => void;
  onSave: () => void;
  saveLabel?: string;
}) {
  const visibilityChosen = explicitlySelected.has('visibility');
  const primaryChosen = explicitlySelected.has('primary_action');
  const highlightChosen = explicitlySelected.has('highlight_recommendation');
  const isAbsent = visibilityChosen && gt.visibility === 'absent';
  const interaction = gt.observed_actions.some((a) => a.endsWith('_interaction'));
  const wheelChosen = gt.enrichment_object === 'wheel';
  const allowedTargets = allowedTargetsFor(gt.primary_action);
  const targetPrompt = targetPromptFor(gt.primary_action);
  // 촬영 환경 '해당 없음'은 UI 전용 상태(설계 §4.1): 직접 확인했고(context_tags 직접 선택)
  // 태그가 하나도 없을 때만 활성. 확인 전(직접 선택 없음)과 화면에서 구분한다.
  const contextConfirmed = explicitlySelected.has('context_tags');
  const contextConfirmedNone = contextConfirmed && gt.context_tags.length === 0;
  // 급여 도구/일반 사물이 모두 대상 후보일 때만 두 범주 경계 안내문을 보여준다(설계 §6.3).
  const showToolObjectNote = allowedTargets.includes('tool') && allowedTargets.includes('object');
  return <Card className="space-y-5">
    <div id={fieldAnchorId('visibility')}><CardTitle>1. 게코가 보이나?</CardTitle><ChoiceRow values={['visible', 'partial', 'absent', 'uncertain']}
      labels={VISIBILITY_LABELS} selected={visibilityChosen ? gt.visibility : ''}
      onSelect={(v) => onSelectVisibility(v as Visibility)} /><FieldError issues={issues} field="visibility" /></div>
    <div id={fieldAnchorId('primary_action')}><CardTitle>2. 이 영상의 대표 행동은?</CardTitle>
      <p className="mt-1 text-xs text-zinc-500">영상에서 가장 중요하게 보이는 행동 하나를 골라줘. 아래 항목에 해당하지 않으면 <strong>일반 이동</strong>으로 선택해. 실제로 본 세부 동작은 아래 3번에 따로 기록해.</p>
      <div className="mt-2 grid grid-cols-2 gap-2">{PRIMARY_ACTIONS.map((action) =>
        <Choice key={action} active={primaryChosen && gt.primary_action === action} onClick={() => patchGt('primary_action', action)}>
          {ACTION_LABELS[action]}{action === 'shedding' && <small className="block text-[10px] opacity-70">허물이 실제로 벗겨짐</small>}
        </Choice>)}</div>
      {primaryChosen && PRIMARY_HELP[gt.primary_action] && <p className="mt-2 rounded-md bg-zinc-100 px-3 py-2 text-xs text-zinc-600">{PRIMARY_HELP[gt.primary_action]}</p>}
      <FieldError issues={issues} field="primary_action" />
    </div>
    {gt.primary_action === 'hand_feeding' && primaryChosen && <div className="rounded-lg bg-amber-50 p-4 ring-1 ring-amber-200">
      <CardTitle>사람이 직접 먹인 근거</CardTitle>
      <p className="mt-1 text-xs text-amber-800">손이나 급여 도구가 보이는 것만으로는 부족해. 먹이가 게코 입으로 직접 전달되는 장면이어야 해.</p>
      <ul className="mt-2 space-y-1 text-xs">
        <ChecklistItem done={gt.observed_actions.some((a) => a === 'licking' || a === 'prey_capture')}>실제 세부 동작(3번)에 핥기 또는 먹이 포획이 있음</ChecklistItem>
        <ChecklistItem done={gt.target === 'hand' || gt.target === 'tool'}>먹인 방법이 손 또는 급여 도구</ChecklistItem>
        <ChecklistItem done={gt.context_tags.includes('human')}>촬영 환경에 사람 등장</ChecklistItem>
      </ul>
    </div>}
    {isAbsent ? (
      <div className="rounded-lg bg-zinc-100 p-4 text-sm text-zinc-600">
        <p><strong>게코가 안 보임</strong>으로 골랐어. 대표 행동은 <strong>안 보임</strong>으로 자동 정리됐어.</p>
        <p className="mt-1 text-xs">세부 동작·동작 시간·행동 대상·놀이 근거·하이라이트 여부는 <strong>해당 없음</strong>이야.</p>
      </div>
    ) : (
      <>
        <div id={fieldAnchorId('observed_actions')}><CardTitle>3. 영상에서 확인한 모든 동작과 시간</CardTitle>
          <p className="mt-1 text-xs text-zinc-500">대표 행동과 별개로 게코가 실제로 한 동작을 모두 선택해. 동작을 선택하면 그 동작이 시작한 시간과 끝난 시간을 입력해.</p>
          <p className="mt-1 text-xs text-zinc-400">예) 영상 전체에서 핥았다면 ‘영상 전체’로 표시돼.</p>
          <div className="mt-2 flex flex-wrap gap-2">{OBSERVED_ACTIONS.map((action) =>
            <Choice key={action} active={gt.observed_actions.includes(action)} onClick={() => toggleObserved(action)}>{OBSERVED_LABELS[action]}</Choice>)}</div>
          <FieldError issues={issues} field="observed_actions" />
          <div id={fieldAnchorId('segments')} className="mt-3 space-y-2">{gt.segments.map((segment) =>
            <SegmentRow key={segment.action} segment={segment} duration={duration} onChange={updateSegment} />)}
            <FieldError issues={issues} field="segments" /></div>
        </div>
        <div id={fieldAnchorId('target')}><CardTitle>{targetPrompt.title}</CardTitle>
          <p className="mt-1 text-xs text-zinc-500">{targetPrompt.description}</p>
          {showToolObjectNote && <p className="mt-1 text-xs text-zinc-500">{TARGET_TOOL_OBJECT_NOTE}</p>}
          <p className="mt-1 text-xs text-zinc-400">{TARGET_PROMPT_COMMON_NOTE}</p>
          <select value={gt.target} onChange={(e) => patchGt('target', e.target.value as Target)}
            className="mt-2 w-full rounded-lg border border-zinc-300 bg-white p-2.5 text-sm font-normal">
            {targetOptions(gt.target, allowedTargets).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
          <FieldError issues={issues} field="target" />
        </div>
      </>
    )}
    <div className="grid gap-4 sm:grid-cols-2">
      <SelectField label="이 판단이 얼마나 확실한가?" value={gt.human_confidence}
        onChange={(v) => patchGt('human_confidence', v as GroundTruthInput['human_confidence'])}
        options={[["certain", CONFIDENCE_LABELS.certain], ["likely", CONFIDENCE_LABELS.likely], ["uncertain", CONFIDENCE_LABELS.uncertain], ["unjudgeable", CONFIDENCE_LABELS.unjudgeable]]} />
    </div>
    {!isAbsent && <div id={fieldAnchorId('highlight_recommendation')}><CardTitle>하이라이트 여부</CardTitle>
      <p className="mt-1 text-xs text-zinc-500">이 영상이 고객에게 보여줄 만한 장면인지 골라줘. 일반 이동이라도 움직임이 크거나 눈에 띄면 <strong>포함</strong>할 수 있어. 탈피·달리기·핥기·먹이 포획처럼 의미 있는 행동도 <strong>포함</strong>으로 선택해. 잘 모르겠으면 <strong>애매</strong>를 골라줘.</p>
      <ChoiceRow values={HIGHLIGHT_RECOMMENDATIONS} labels={HIGHLIGHT_LABELS}
        selected={highlightChosen ? gt.highlight_recommendation : ''} onSelect={(v) => patchGt('highlight_recommendation', v as HighlightRecommendation)} />
      <FieldError issues={issues} field="highlight_recommendation" /></div>}
    <div id={fieldAnchorId('context_tags')}><CardTitle>{CONTEXT_TAGS_TITLE}</CardTitle>
      <p className="mt-1 text-xs text-zinc-500">{CONTEXT_TAGS_HELP}</p>
      <div className="mt-2 flex flex-wrap gap-2">{CONTEXT_TAGS.map((tag) =>
        <Choice key={tag} active={gt.context_tags.includes(tag)} onClick={() => patchGt('context_tags',
          gt.context_tags.includes(tag) ? gt.context_tags.filter((x) => x !== tag) : [...gt.context_tags, tag])}>{CONTEXT_LABELS[tag]}</Choice>)}
        {/* '해당 없음'은 태그와 상호 배타(설계 §5.1·§7.1 규칙4·5): 누르면 모든 태그를 지워 빈 배열로 확정한다. */}
        <Choice active={contextConfirmedNone} onClick={() => patchGt('context_tags', [])}>{CONTEXT_TAGS_NONE_LABEL}</Choice></div>
      <FieldError issues={issues} field="context_tags" /></div>
    {!isAbsent && interaction && <div id={fieldAnchorId('enrichment_object')} className="rounded-lg bg-violet-50 p-4 ring-1 ring-violet-200">
      <CardTitle>놀이로 볼 수 있는 행동 근거</CardTitle><p className="mt-1 text-xs text-violet-700">게코가 쳇바퀴나 사물을 실제로 사용했다면, 무엇을 사용했고 어떻게 사용했는지 모두 기록해.</p>
      <p className="mt-3 text-xs font-medium text-violet-900">1. 사용한 사물 선택</p>
      <div className="mt-1"><ChoiceRow values={['wheel','toy','other','uncertain']} labels={ENRICHMENT_LABELS}
        selected={gt.enrichment_object === 'none' ? '' : gt.enrichment_object} onSelect={(v) => patchGt('enrichment_object', v as GroundTruthInput['enrichment_object'])} /></div>
      <FieldError issues={issues} field="enrichment_object" />
      <p className="mt-3 text-xs font-medium text-violet-900">2. 사용한 방법 선택 · 하나 이상 필수</p>
      {wheelChosen && <p className="mt-1 text-xs text-violet-700">쳇바퀴를 선택했다면 <strong>올라타기·밀기·회전시키기</strong> 중 실제로 확인한 방법을 하나 이상 골라줘.</p>}
      <div className="mt-1 flex flex-wrap gap-2">{INTERACTION_TYPES.map((type) =>
        <Choice key={type} active={gt.interaction_types.includes(type)} onClick={() => patchGt('interaction_types',
          gt.interaction_types.includes(type) ? gt.interaction_types.filter((x) => x !== type) : [...gt.interaction_types, type])}>{INTERACTION_LABELS[type]}</Choice>)}</div>
      <FieldError issues={issues} field="interaction_types" />
    </div>}
    <label className="block text-sm font-medium">메모 (선택)<textarea value={gt.note ?? ''}
      onChange={(e) => patchGt('note', e.target.value || null)} maxLength={2000}
      className="mt-2 min-h-20 w-full rounded-lg border border-zinc-300 p-3 font-normal outline-none focus:border-zinc-900" /></label>
    <div className="rounded-lg bg-amber-50 p-3 text-xs text-amber-900">저장하면 되돌릴 수 없습니다. 저장후 AI가 판단한 정보를 표시해 드리겠습니다</div>
    <Button size="lg" className="w-full" disabled={saving} onClick={onSave}>{saving ? '저장 중…' : (saveLabel ?? '사람 판정 저장하고 AI 판정 보기')}</Button>
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

export function VlmReviewCard({ prediction, humanGt, review, setReview, saving, completed, onComplete, completeLabel, owner = false }: {
  prediction: Record<string, unknown>; humanGt: GroundTruthInput; review: VlmReviewInput;
  setReview: (value: VlmReviewInput) => void; saving: boolean; completed: boolean; onComplete: () => void;
  completeLabel?: string; owner?: boolean;
}) {
  const action = String(prediction.action ?? 'unknown');
  // 미지 VLM action(출력 클래스 등)도 raw 영문 대신 '확인 필요'로(하드닝 §7).
  const actionLabel = formatActionLabel(action);
  const sheddingConfirmed = action === 'shedding' && humanGt.primary_action === 'shedding';
  return <Card className="space-y-4 border-sky-200">
    <div><Badge tone="info">사람 판정 저장 후 공개</Badge><CardTitle className="mt-2">영상 분석 AI의 판정</CardTitle></div>
    <div className="rounded-lg bg-zinc-950 p-4 text-zinc-50">
      <div className="text-lg font-semibold">{action === 'shedding' ? (sheddingConfirmed ? '탈피 확인' : 'AI 탈피 의심 · 확인 필요') : actionLabel}</div>
      <div className="mt-1 text-xs text-zinc-400">AI 확신도 {String(prediction.confidence ?? '없음')}{owner ? ` · ${String(prediction.vlm_model ?? 'model 미기록')}` : ''}</div>
      {/* AI raw reasoning 은 영어·내부 용어를 담을 수 있어 일반 라벨러에게 노출하지 않는다(하드닝 §7). owner 기술 정보에서만 확인. */}
      {owner && prediction.reasoning ? <p className="mt-3 whitespace-pre-wrap text-sm text-zinc-300">{String(prediction.reasoning)}</p> : null}
      {owner && <details className="mt-3 text-xs text-zinc-400"><summary className="cursor-pointer">기술 정보 (owner 전용 · 정확한 reasoning·model·snapshot 전체)</summary><pre className="mt-2 overflow-auto whitespace-pre-wrap">{JSON.stringify(prediction, null, 2)}</pre></details>}
    </div>
    <div><CardTitle>AI 판정 비교</CardTitle>
      <p className="mt-1 text-xs text-zinc-500">위에 표시된 AI의 대표 행동과 내가 저장한 대표 행동을 비교해. AI가 말하지 않은 세부 동작이나 놀이 정보는 여기서 감점하지 않아.</p>
      <ChoiceRow values={VERDICT_ORDER}
      labels={VERDICT_LABELS} selected={review.verdict} onSelect={(v) => setReview({...review, verdict:v as VlmVerdict})} />
      <dl className="mt-2 space-y-0.5 text-[11px] text-zinc-500">{VERDICT_ORDER.map((v) =>
        <div key={v}><dt className="inline font-medium text-zinc-600">{VERDICT_LABELS[v]}</dt><dd className="inline"> — {VERDICT_HELP[v]}</dd></div>)}</dl></div>
    {(review.verdict === 'incorrect' || review.verdict === 'partially_correct') && <div>
      <CardTitle>어디가 달랐어? (하나 이상)</CardTitle>
      <p className="mt-1 text-xs text-zinc-500">AI 판정은 대표 행동 하나만 내. ‘복수 행동 누락’은 지금은 고르지 않아도 돼.</p>
      <div className="mt-2 flex flex-wrap gap-2">{VLM_ERROR_TAGS.map((tag) =>
        <Choice key={tag} active={review.error_tags.includes(tag)} onClick={() => setReview({...review, error_tags:
          review.error_tags.includes(tag) ? review.error_tags.filter((x) => x !== tag) : [...review.error_tags, tag]})}>{ERROR_LABELS[tag]}</Choice>)}</div></div>}
    <label className="block text-sm font-medium">검수 메모 (선택)<textarea value={review.note ?? ''}
      onChange={(e) => setReview({...review, note:e.target.value || null})} maxLength={2000}
      className="mt-2 min-h-16 w-full rounded-lg border border-zinc-300 p-3 font-normal" /></label>
    {!completed && <Button size="lg" className="w-full" disabled={saving} onClick={onComplete}>{saving ? '저장 중…' : (completeLabel ?? '검수 완료하고 다음 영상')}</Button>}
  </Card>;
}

export function GtSummary({ gt, duration }: { gt: GroundTruthInput; duration?: number }) {
  // legacy GT(하드닝 §1): highlight 가 있으면 하이라이트 결과를, 없으면 기존 활동 강도를 한국어로,
  // 둘 다 없으면 해당 항목을 안전하게 생략한다. undefined 가 절대 렌더되지 않게 한다.
  const highlightClause = highlightSummaryClause(gt);
  return <Card className="border-emerald-200 bg-emerald-50"><div className="flex items-center justify-between"><CardTitle>AI를 보기 전에 저장한 사람 판정</CardTitle><Badge tone="success">AI 영향 없이 기록됨</Badge></div>
    <p className="mt-2 text-sm text-emerald-950"><strong>{formatActionLabel(gt.primary_action)}</strong> · {VISIBILITY_LABELS[gt.visibility] ?? UNKNOWN_LABEL}{highlightClause ? ` · ${highlightClause}` : ''}</p>
    <p className="mt-1 text-xs text-emerald-800">{gt.observed_actions.map((a) => OBSERVED_LABELS[a] ?? UNKNOWN_LABEL).join(' · ') || '기록한 세부 동작 없음'}</p>
    {gt.segments.length > 0 && <p className="mt-1 text-xs text-emerald-800">{gt.segments.map((s) => describeSegment(s, duration)).join(' · ')}</p>}</Card>;
}

export function MetadataCard({ metadata, clipId }: { metadata: Record<string, unknown>; clipId: string }) {
  return <Card padding="sm"><details><summary className="cursor-pointer text-sm font-medium">시스템 메타데이터</summary>
    <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-xs">{Object.entries(metadata).map(([key,value]) =>
      <div key={key}><dt className="text-zinc-500">{key}</dt><dd className="truncate font-mono">{String(value ?? '—')}</dd></div>)}</dl>
    <p className="mt-2 truncate font-mono text-[10px] text-zinc-400">{clipId}</p></details></Card>;
}

export function SegmentRow({ segment, duration, onChange }: { segment: ActionSegment; duration: number;
  onChange: (action: ObservedAction, key: 'start_sec' | 'end_sec', value: number) => void }) {
  // 끝이 영상 끝(실제 duration)이면 raw 31.7999 대신 '영상 끝 (31.8초)' 칩을 보여준다(하드닝 §2).
  // '직접 입력'을 누르면 숫자 입력으로 전환한다. 저장값은 항상 실제 duration 을 유지한다.
  const [manualEnd, setManualEnd] = useState(false);
  const atEnd = isVideoEnd(segment.end_sec, duration);
  return <div className="rounded-lg bg-zinc-50 p-2 text-xs">
    <p className="mb-1.5 font-medium text-zinc-600">{describeSegment(segment, duration)}</p>
    <div className="grid grid-cols-[auto_1fr_auto_1.4fr] items-center gap-2">
      <span className="text-zinc-500">시작</span>
      <input type="number" min={0} max={duration} step="0.1" value={segment.start_sec}
        onChange={(e) => onChange(segment.action,'start_sec',Number(e.target.value))} className="w-full rounded border p-1.5"/>
      <span className="text-zinc-500">끝</span>
      {atEnd && !manualEnd ? (
        <button type="button" onClick={() => setManualEnd(true)}
          className="w-full rounded border border-zinc-300 bg-white p-1.5 text-left text-zinc-600">
          {formatVideoEndLabel(duration)} · 직접 입력
        </button>
      ) : (
        <div className="flex items-center gap-1">
          <input type="number" min={0} max={duration} step="0.1" value={segment.end_sec}
            onChange={(e) => onChange(segment.action,'end_sec',Number(e.target.value))} className="w-full rounded border p-1.5"/>
          <button type="button" onClick={() => { onChange(segment.action,'end_sec',duration); setManualEnd(false); }}
            className="shrink-0 rounded border border-zinc-300 px-1.5 py-1 text-[10px] text-zinc-500">영상 끝</button>
        </div>
      )}
    </div>
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
