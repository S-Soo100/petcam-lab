import { describe, expect, it } from 'vitest';

import { compareTutorialAnswers, deepEqualAnswer } from './labelingTutorial';
import type { GroundTruthInput, VlmReviewInput } from './labelingV2';

const baseGt: GroundTruthInput = {
  visibility: 'visible',
  primary_action: 'drinking',
  observed_actions: ['licking'],
  segments: [{ action: 'licking', start_sec: 2, end_sec: 8 }],
  target: 'water',
  human_confidence: 'certain',
  context_tags: ['ir'],
  activity_intensity: 'low',
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

  it('aggregate pass/fail/score 를 계산하지 않는다', () => {
    const cmp = compareTutorialAnswers(baseGt, baseReview, baseGt, baseReview);
    expect(cmp).not.toHaveProperty('score');
    expect(cmp).not.toHaveProperty('passed');
    expect(Object.keys(cmp)).toEqual(['dimensions']);
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
