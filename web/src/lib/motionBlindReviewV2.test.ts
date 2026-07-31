import { describe, expect, it } from 'vitest';
import type { GroundTruthInput } from './labelingV2';
import {
  compareBlindSubmissions,
  type BlindSubmissionInput,
} from './motionBlindReview';
import {
  LIVE_V2_COMPARATOR_VERSION,
  compareBlindSubmissionsByVersion,
} from './motionBlindReviewV2';

function gt(overrides: Partial<GroundTruthInput> = {}): GroundTruthInput {
  return {
    visibility: 'visible',
    primary_action: 'moving',
    observed_actions: ['moving'],
    segments: [{ action: 'moving', start_sec: 0, end_sec: 1 }],
    target: 'none',
    human_confidence: 'certain',
    context_tags: [],
    activity_intensity: null,
    highlight_recommendation: 'exclude',
    enrichment_object: 'none',
    interaction_types: [],
    note: null,
    ...overrides,
  };
}

function label(overrides: Partial<GroundTruthInput> = {}): BlindSubmissionInput {
  return {
    decision: 'label',
    initial_gt: gt(overrides),
    note: null,
    reason_code: 'behavior_data',
  };
}

describe('live highlight-soft comparator dispatcher', () => {
  it('keeps motion-blind-v1 behavior byte-for-byte equivalent', () => {
    const a = label({ highlight_recommendation: 'include' });
    const b = label({ highlight_recommendation: 'exclude' });
    expect(compareBlindSubmissionsByVersion('motion-blind-v1', a, b)).toEqual(
      compareBlindSubmissions(a, b),
    );
  });

  it('rejects an unknown comparator version', () => {
    expect(() =>
      compareBlindSubmissionsByVersion('unknown' as never, label(), label()),
    ).toThrow('unknown_blind_comparator_version');
  });

  it('merges a highlight-only difference to uncertain agreement', () => {
    const result = compareBlindSubmissionsByVersion(
      LIVE_V2_COMPARATOR_VERSION,
      label({ highlight_recommendation: 'include' }),
      label({ highlight_recommendation: 'exclude' }),
    );
    expect(result).toMatchObject({
      status: 'agreed',
      final_decision: 'label',
      differing_fields: ['highlight_recommendation'],
      comparator_version: LIVE_V2_COMPARATOR_VERSION,
    });
    expect(result.final_gt?.highlight_recommendation).toBe('uncertain');
  });

  it('keeps highlight plus core differences as conflict', () => {
    const result = compareBlindSubmissionsByVersion(
      LIVE_V2_COMPARATOR_VERSION,
      label({ primary_action: 'moving', highlight_recommendation: 'include' }),
      label({ primary_action: 'drinking', highlight_recommendation: 'exclude' }),
    );
    expect(result).toMatchObject({
      status: 'conflict',
      differing_fields: ['primary_action', 'highlight_recommendation'],
      comparator_version: LIVE_V2_COMPARATOR_VERSION,
    });
  });

  it('keeps wheel interaction differences as conflict', () => {
    const result = compareBlindSubmissionsByVersion(
      LIVE_V2_COMPARATOR_VERSION,
      label({
        observed_actions: ['wheel_interaction'],
        segments: [{ action: 'wheel_interaction', start_sec: 0, end_sec: 1 }],
        enrichment_object: 'wheel',
        interaction_types: ['ride'],
      }),
      label({
        observed_actions: ['wheel_interaction'],
        segments: [{ action: 'wheel_interaction', start_sec: 0, end_sec: 1 }],
        enrichment_object: 'wheel',
        interaction_types: ['rotate'],
      }),
    );
    expect(result).toMatchObject({
      status: 'conflict',
      differing_fields: ['interaction_types'],
    });
  });

  it('keeps the 500ms segment boundary', () => {
    const within = compareBlindSubmissionsByVersion(
      LIVE_V2_COMPARATOR_VERSION,
      label({ segments: [{ action: 'moving', start_sec: 1, end_sec: 2 }] }),
      label({ segments: [{ action: 'moving', start_sec: 1.5, end_sec: 2.5 }] }),
    );
    const outside = compareBlindSubmissionsByVersion(
      LIVE_V2_COMPARATOR_VERSION,
      label({ segments: [{ action: 'moving', start_sec: 1, end_sec: 2 }] }),
      label({ segments: [{ action: 'moving', start_sec: 1.501, end_sec: 2 }] }),
    );
    expect(within.status).toBe('agreed');
    expect(outside).toMatchObject({
      status: 'conflict',
      differing_fields: ['segments'],
    });
  });
});
