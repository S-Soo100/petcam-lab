// 라벨링 대화형 튜토리얼 — 공유 타입 + 답안 비교 순수 함수(설계 §10).
//
// 이 모듈은 client/server 공용(순수 로직). DB 접근은 labelingTutorialGate.ts(server-only).
// 비교는 aggregate pass/fail 을 계산하지 않는다 — dimension 을 matched/review/subjective
// 세 그룹으로만 분류한다. '왜'/'다음 영상에서' 문구는 lesson.feedback_content 에서 병합한다.

import type { ActionSegment, GroundTruthInput, VlmReviewInput } from './labelingV2';

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
  exact('activity_intensity', yoursGt.activity_intensity, refGt.activity_intensity);
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
