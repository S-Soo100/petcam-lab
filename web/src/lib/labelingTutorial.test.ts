import { describe, expect, it } from 'vitest';

import {
  compareTutorialAnswers,
  deepEqualAnswer,
  evaluateTutorialReferenceSemantics,
} from './labelingTutorial';
import type { GroundTruthInput, VlmReviewInput } from './labelingV2';

const baseGt: GroundTruthInput = {
  visibility: 'visible',
  primary_action: 'drinking',
  observed_actions: ['licking'],
  segments: [{ action: 'licking', start_sec: 2, end_sec: 8 }],
  target: 'water',
  human_confidence: 'certain',
  context_tags: ['ir'],
  activity_intensity: null,
  highlight_recommendation: 'include',
  enrichment_object: 'none',
  interaction_types: [],
  note: null,
};
const baseReview: VlmReviewInput = {
  verdict: 'incorrect',
  error_tags: ['action_confusion'],
  note: null,
};

function dim(gt: GroundTruthInput, review: VlmReviewInput, key: string) {
  return compareTutorialAnswers(gt, review, baseGt, baseReview).dimensions.find(
    (d) => d.key === key,
  )!;
}

describe('compareTutorialAnswers', () => {
  it('exact 필드가 같으면 matched', () => {
    expect(dim(baseGt, baseReview, 'primary_action').group).toBe('matched');
  });

  it('exact 필드 불일치는 review 로 분류한다', () => {
    expect(dim({ ...baseGt, primary_action: 'moving' }, baseReview, 'primary_action').group).toBe(
      'review',
    );
  });

  it('set 필드는 순서 무관 동일 집합이면 matched', () => {
    const ref = compareTutorialAnswers(
      { ...baseGt, observed_actions: ['moving', 'licking'] },
      baseReview,
      { ...baseGt, observed_actions: ['licking', 'moving'] },
      baseReview,
    );
    expect(ref.dimensions.find((d) => d.key === 'observed_actions')!.group).toBe('matched');
  });

  it('set 필드 다른 집합은 review', () => {
    expect(dim({ ...baseGt, observed_actions: ['moving'] }, baseReview, 'observed_actions').group).toBe(
      'review',
    );
  });

  it('segment 는 같은 action start/end 1초 이내면 matched', () => {
    const yours = { ...baseGt, segments: [{ action: 'licking' as const, start_sec: 2.7, end_sec: 8.9 }] };
    expect(dim(yours, baseReview, 'segments').group).toBe('matched');
  });

  it('segment 오차 1초 초과는 review', () => {
    const yours = { ...baseGt, segments: [{ action: 'licking' as const, start_sec: 2, end_sec: 10.5 }] };
    expect(dim(yours, baseReview, 'segments').group).toBe('review');
  });

  it('segment 개수가 다르면 review', () => {
    const yours = {
      ...baseGt,
      segments: [
        { action: 'licking' as const, start_sec: 2, end_sec: 8 },
        { action: 'licking' as const, start_sec: 9, end_sec: 10 },
      ],
    };
    expect(dim(yours, baseReview, 'segments').group).toBe('review');
  });

  it('VLM verdict/error_tags 도 비교한다', () => {
    const cmp = compareTutorialAnswers(baseGt, { ...baseReview, verdict: 'correct' }, baseGt, baseReview);
    expect(cmp.dimensions.find((d) => d.key === 'vlm_verdict')!.group).toBe('review');
  });

  it('human_confidence/context_tags/note 는 subjective', () => {
    for (const key of ['human_confidence', 'context_tags', 'note']) {
      expect(dim({ ...baseGt, human_confidence: 'likely' }, baseReview, key).group).toBe('subjective');
    }
  });

  it('highlight_recommendation 을 exact 비교한다 (§6.3)', () => {
    expect(dim(baseGt, baseReview, 'highlight_recommendation').group).toBe('matched');
    expect(
      dim({ ...baseGt, highlight_recommendation: 'exclude' }, baseReview, 'highlight_recommendation')
        .group,
    ).toBe('review');
  });

  it('legacy activity_intensity 는 비교 dimension 에서 제외한다 (§6.3)', () => {
    // 값이 달라도 activity 는 이제 비교하지 않는다 — dimension 자체가 없어야 한다.
    const cmp = compareTutorialAnswers(
      { ...baseGt, activity_intensity: 'high' },
      baseReview,
      baseGt,
      baseReview,
    );
    expect(cmp.dimensions.find((d) => d.key === 'activity_intensity')).toBeUndefined();
  });

  it('aggregate pass/fail/score 를 계산하지 않는다', () => {
    const cmp = compareTutorialAnswers(baseGt, baseReview, baseGt, baseReview);
    expect(cmp).not.toHaveProperty('score');
    expect(cmp).not.toHaveProperty('passed');
    expect(Object.keys(cmp)).toEqual(['dimensions']);
  });
});

describe('evaluateTutorialReferenceSemantics (§8.2 fixture)', () => {
  const gt = (o: Partial<GroundTruthInput>): GroundTruthInput => ({
    visibility: 'visible', primary_action: 'moving', observed_actions: [], segments: [],
    target: 'none', human_confidence: 'certain', context_tags: [], activity_intensity: null,
    highlight_recommendation: 'include',
    enrichment_object: 'none', interaction_types: [], note: null, ...o,
  });
  const noReview = { verdict: 'correct', error_tags: [] as string[] };

  const REFERENCES: Array<{
    position: number; refGt: GroundTruthInput;
    prediction: { action?: unknown } | null; review: { verdict: string; error_tags: string[] };
  }> = [
    { position: 1, refGt: gt({ visibility: 'absent', primary_action: 'unseen' }), prediction: null, review: noReview },
    { position: 2, refGt: gt({ primary_action: 'moving', observed_actions: ['moving'], segments: [{ action: 'moving', start_sec: 0, end_sec: 5 }] }), prediction: null, review: noReview },
    { position: 3, refGt: gt({ primary_action: 'drinking', observed_actions: ['moving', 'wheel_interaction'], segments: [{ action: 'moving', start_sec: 0, end_sec: 4 }, { action: 'wheel_interaction', start_sec: 5, end_sec: 8 }], target: 'water_bowl', enrichment_object: 'wheel', interaction_types: ['ride'] }), prediction: null, review: noReview },
    { position: 4, refGt: gt({ primary_action: 'hand_feeding', observed_actions: ['licking'], segments: [{ action: 'licking', start_sec: 0, end_sec: 5 }], target: 'hand', context_tags: ['human'] }), prediction: null, review: noReview },
    { position: 5, refGt: gt({ primary_action: 'drinking', observed_actions: ['licking'], segments: [{ action: 'licking', start_sec: 0, end_sec: 5 }], target: 'water' }), prediction: { action: 'shedding' }, review: { verdict: 'incorrect', error_tags: ['morph_confusion'] } },
  ];

  it('accepts all five correctly-shaped references', () => {
    for (const r of REFERENCES) {
      const result = evaluateTutorialReferenceSemantics(r.position, r.refGt, r.prediction, r.review);
      expect(result, `position ${r.position}`).toEqual({ ok: true, reason: null });
    }
  });

  it('rejects position 3 when the target is tool (wheel is not a target)', () => {
    const r = REFERENCES[2];
    const result = evaluateTutorialReferenceSemantics(3, { ...r.refGt, target: 'tool' }, r.prediction, r.review);
    expect(result.ok).toBe(false);
  });

  it('rejects position 3 when the primary action is not drinking (moving+wheel)', () => {
    // 단순 wheel evidence 만으로는 부족 — lesson 3 은 drinking 대표 행동을 전제한다.
    const r = REFERENCES[2];
    const result = evaluateTutorialReferenceSemantics(3, { ...r.refGt, primary_action: 'moving' }, r.prediction, r.review);
    expect(result.ok).toBe(false);
  });

  it('rejects position 3 when the target is not a water target', () => {
    const r = REFERENCES[2];
    const result = evaluateTutorialReferenceSemantics(3, { ...r.refGt, target: 'none' }, r.prediction, r.review);
    expect(result.ok).toBe(false);
  });

  it('rejects position 4 when the human context tag is missing', () => {
    const r = REFERENCES[3];
    const result = evaluateTutorialReferenceSemantics(4, { ...r.refGt, context_tags: [] }, r.prediction, r.review);
    expect(result.ok).toBe(false);
  });

  it('rejects position 5 when the VLM did not output shedding', () => {
    const r = REFERENCES[4];
    const result = evaluateTutorialReferenceSemantics(5, r.refGt, { action: 'moving' }, r.review);
    expect(result.ok).toBe(false);
  });

  it('rejects a reference placed at the wrong position', () => {
    // 일반 이동 reference 를 position 1(unseen)에 두면 실패.
    expect(evaluateTutorialReferenceSemantics(1, REFERENCES[1].refGt, null, noReview).ok).toBe(false);
  });
});

describe('deepEqualAnswer', () => {
  it('키 순서 무관 deep-equal', () => {
    expect(deepEqualAnswer({ a: 1, b: [1, 2] }, { b: [1, 2], a: 1 })).toBe(true);
  });
  it('값이 다르면 false', () => {
    expect(deepEqualAnswer({ a: 1 }, { a: 2 })).toBe(false);
  });
  it('배열 순서 차이는 다르다', () => {
    expect(deepEqualAnswer([1, 2], [2, 1])).toBe(false);
  });
  it('null 과 객체 구분', () => {
    expect(deepEqualAnswer(null, {})).toBe(false);
    expect(deepEqualAnswer(null, null)).toBe(true);
  });
});
