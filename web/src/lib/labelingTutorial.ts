// 라벨링 대화형 튜토리얼 — 공유 타입 + 답안 비교 순수 함수(설계 §10).
//
// 이 모듈은 client/server 공용(순수 로직). DB 접근은 labelingTutorialGate.ts(server-only).
// 비교는 aggregate pass/fail 을 계산하지 않는다 — dimension 을 matched/review/subjective
// 세 그룹으로만 분류한다. '왜'/'다음 영상에서' 문구는 lesson.feedback_content 에서 병합한다.

import {
  DRINKING_TARGETS,
  type ActionSegment,
  type GroundTruthInput,
  type ObservedAction,
  type VlmReviewInput,
} from './labelingV2';

export type DimensionGroup = 'matched' | 'review' | 'subjective';

export interface DimensionResult {
  key: string;
  group: DimensionGroup;
  yours: unknown;
  reference: unknown;
}

export interface TutorialComparison {
  dimensions: DimensionResult[];
}

// segment start/end 허용 오차(설계 §10: 같은 action 끼리 1초 이내면 일치).
const SEGMENT_TOLERANCE_SEC = 1;

// exact: 스칼라 동일. set: 순서 무관 동일 집합. segment: 같은 action start/end 1초 이내.
// subjective: 참고만(human_confidence, context_tags, note).
export function compareTutorialAnswers(
  yoursGt: GroundTruthInput,
  yoursReview: VlmReviewInput,
  refGt: GroundTruthInput,
  refReview: VlmReviewInput,
): TutorialComparison {
  const dims: DimensionResult[] = [];
  const exact = (key: string, a: unknown, b: unknown) =>
    dims.push({ key, group: a === b ? 'matched' : 'review', yours: a, reference: b });
  const set = (key: string, a: readonly string[], b: readonly string[]) =>
    dims.push({ key, group: sameSet(a, b) ? 'matched' : 'review', yours: a, reference: b });
  const subjective = (key: string, a: unknown, b: unknown) =>
    dims.push({ key, group: 'subjective', yours: a, reference: b });

  exact('visibility', yoursGt.visibility, refGt.visibility);
  exact('primary_action', yoursGt.primary_action, refGt.primary_action);
  exact('target', yoursGt.target, refGt.target);
  // v2 비교는 highlight_recommendation 을 비교하고 legacy activity_intensity 는 비교하지 않는다(설계 §6.3).
  // absent reference 는 highlight 가 'exclude'로 정규화되므로 exact 비교로도 무해하게 일치한다.
  exact('highlight_recommendation', yoursGt.highlight_recommendation, refGt.highlight_recommendation);
  exact('enrichment_object', yoursGt.enrichment_object, refGt.enrichment_object);
  set('observed_actions', yoursGt.observed_actions, refGt.observed_actions);
  set('interaction_types', yoursGt.interaction_types, refGt.interaction_types);
  dims.push({
    key: 'segments',
    group: segmentsMatch(yoursGt.segments, refGt.segments) ? 'matched' : 'review',
    yours: yoursGt.segments,
    reference: refGt.segments,
  });
  exact('vlm_verdict', yoursReview.verdict, refReview.verdict);
  set('vlm_error_tags', yoursReview.error_tags, refReview.error_tags);
  subjective('human_confidence', yoursGt.human_confidence, refGt.human_confidence);
  subjective('context_tags', yoursGt.context_tags, refGt.context_tags);
  subjective('note', yoursGt.note, refGt.note);

  return { dimensions: dims };
}

function sameSet(a: readonly string[], b: readonly string[]): boolean {
  if (a.length !== b.length) return false;
  const sb = new Set(b);
  return a.every((x) => sb.has(x));
}

// 각 기준 segment 에 같은 action + start/end 1초 이내 매칭이 있고 개수도 같아야 matched.
// 하나의 제출 segment 를 두 기준에 중복 매칭시키지 않도록 used 로 표시한다.
function segmentsMatch(yours: ActionSegment[], ref: ActionSegment[]): boolean {
  if (yours.length !== ref.length) return false;
  const used = new Array(yours.length).fill(false);
  return ref.every((r) => {
    const i = yours.findIndex(
      (y, idx) =>
        !used[idx] &&
        y.action === r.action &&
        Math.abs(y.start_sec - r.start_sec) <= SEGMENT_TOLERANCE_SEC &&
        Math.abs(y.end_sec - r.end_sec) <= SEGMENT_TOLERANCE_SEC,
    );
    if (i === -1) return false;
    used[i] = true;
    return true;
  });
}

// ── 튜토리얼 reference 의미 사전검사(설계 §8.2) ────────────────────
//
// ⚠️ SOT 는 SQL `fn_seed_tutorial_lesson_from_owner`(_hardening_4 마이그레이션)이다.
// seed 는 그 함수가 DB 레벨에서 막는다. 이 순수 함수는 같은 규칙을 미러해서 5개
// reference 를 fixture 로 빠르게 검증하고, 필요하면 owner 의 draft preview(§14)에서
// "어느 position 이 왜 안 맞는지"를 미리 보여주는 데 재사용한다. SQL 과 규칙이 어긋나면
// 둘 다 고친다.

export interface TutorialReferenceSemantics {
  ok: boolean;
  reason: string | null;
}

export function evaluateTutorialReferenceSemantics(
  position: number,
  refGt: GroundTruthInput,
  prediction: { action?: unknown } | null,
  review: { verdict: string; error_tags: readonly string[] },
): TutorialReferenceSemantics {
  const observed = refGt.observed_actions;
  const has = (a: ObservedAction) => observed.includes(a);
  let reason: string | null = null;
  switch (position) {
    case 1:
      if (!(refGt.visibility === 'absent' && refGt.primary_action === 'unseen'
        && observed.length === 0 && refGt.segments.length === 0 && refGt.target === 'none')) {
        reason = 'position 1 must be absent/unseen with empty observed+segments and target none';
      }
      break;
    case 2:
      if (!((refGt.visibility === 'visible' || refGt.visibility === 'partial')
        && refGt.primary_action === 'moving' && has('moving')
        && refGt.segments.some((s) => s.action === 'moving'))) {
        reason = 'position 2 must be visible/partial moving with a moving segment';
      }
      break;
    case 3:
      // drinking+wheel: 대표 행동은 drinking, target 은 물 집합(wheel/tool 아님),
      // wheel 은 enrichment_object 로 따로 기록. SQL preflight(_hardening_4.sql)와 동치.
      if (!(refGt.primary_action === 'drinking'
        && DRINKING_TARGETS.includes(refGt.target)
        && has('wheel_interaction') && refGt.enrichment_object === 'wheel'
        && refGt.interaction_types.length >= 1
        && observed.length >= 2)) {
        reason = 'position 3 must be drinking+wheel: primary drinking, target in {water,water_bowl,glass,floor,uncertain}, wheel interaction + enrichment wheel + >=1 interaction type + >=2 observed actions';
      }
      break;
    case 4:
      if (!(refGt.primary_action === 'hand_feeding'
        && (has('licking') || has('prey_capture'))
        && (refGt.target === 'hand' || refGt.target === 'tool')
        && refGt.context_tags.includes('human'))) {
        reason = 'position 4 must be hand_feeding (licking/prey_capture + target hand/tool + context human)';
      }
      break;
    case 5:
      if (!(String(prediction?.action) === 'shedding'
        && refGt.primary_action !== 'shedding'
        && review.verdict === 'incorrect'
        && review.error_tags.length >= 1)) {
        reason = 'position 5 must be a VLM shedding misjudge (VLM action shedding, human primary != shedding, verdict incorrect, >=1 error tag)';
      }
      break;
    default:
      reason = 'position must be 1..5';
  }
  return { ok: reason === null, reason };
}

// idempotency 판정용 — 키 순서 무관 deep-equal(JSON 값 한정: object/array/scalar).
// 배열은 순서를 유지해야 같다(segments 순서는 의미 있음).
export function deepEqualAnswer(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (typeof a !== typeof b) return false;
  if (Array.isArray(a) || Array.isArray(b)) {
    if (!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length) return false;
    return a.every((x, i) => deepEqualAnswer(x, b[i]));
  }
  if (a && b && typeof a === 'object') {
    const ka = Object.keys(a as object).sort();
    const kb = Object.keys(b as object).sort();
    if (ka.length !== kb.length || ka.some((k, i) => k !== kb[i])) return false;
    return ka.every((k) =>
      deepEqualAnswer((a as Record<string, unknown>)[k], (b as Record<string, unknown>)[k]),
    );
  }
  return false;
}

// ── 클라이언트/서버 공유 튜토리얼 타입 ─────────────────────────────

export type TutorialStatus =
  | 'not_started'
  | 'in_progress'
  | 'completed'
  | 'waived'
  | 'unavailable';

// GET /api/labeling-access 의 tutorial 필드(설계 §11). 멤버십(access)과 별도 축.
export interface TutorialAccess {
  required: boolean;
  status: TutorialStatus;
  completed_lessons: number;
  total_lessons: 5;
}

export type TutorialAttemptStage = 'draft' | 'gt_locked' | 'review_submitted' | 'completed';

// lesson 의 dimension별 해설(설계 §10). '왜'/'다음 영상에서' 문구.
export interface DimensionFeedback {
  why?: string;
  next?: string;
}
export type FeedbackContent = Record<string, DimensionFeedback>;
