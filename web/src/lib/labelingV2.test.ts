import { describe, expect, it } from 'vitest';

import {
  BLIND_QUEUE_CLIP_COLUMNS,
  nextStage,
  revealPrediction,
  thumbnailKeyForClip,
  validateGroundTruth,
  validateVlmReview,
  type GroundTruthInput,
} from './labelingV2';

describe('blind queue projection', () => {
  it('matches the deployed camera_clips schema without ended_at', () => {
    const columns = BLIND_QUEUE_CLIP_COLUMNS.split(',');
    expect(columns).toContain('started_at');
    expect(columns).toContain('duration_sec');
    expect(columns).not.toContain('ended_at');
  });
});

function validGt(overrides: Partial<GroundTruthInput> = {}): GroundTruthInput {
  return {
    visibility: 'visible',
    primary_action: 'moving',
    observed_actions: ['moving'],
    segments: [{ action: 'moving', start_sec: 0, end_sec: 4 }],
    target: 'none',
    human_confidence: 'certain',
    context_tags: ['ir'],
    activity_intensity: 'medium',
    enrichment_object: 'none',
    interaction_types: [],
    note: null,
    ...overrides,
  };
}

describe('validateGroundTruth', () => {
  it('accepts ordinary moving without enrichment evidence', () => {
    expect(validateGroundTruth(validGt(), 30)).toEqual(validGt());
  });

  it('rejects absent visibility with a non-unseen primary action', () => {
    expect(() =>
      validateGroundTruth(
        validGt({ visibility: 'absent', primary_action: 'moving' }),
        30,
      ),
    ).toThrow('안 보임');
  });

  it('rejects unseen when the gecko is marked visible', () => {
    expect(() =>
      validateGroundTruth(validGt({ primary_action: 'unseen' }), 30),
    ).toThrow('unseen');
  });

  it('rejects interaction evidence without an object and interaction type', () => {
    expect(() =>
      validateGroundTruth(
        validGt({ observed_actions: ['moving', 'wheel_interaction'] }),
        30,
      ),
    ).toThrow('상호작용 근거');
  });

  it('accepts objective wheel evidence without a playing action', () => {
    const input = validGt({
      observed_actions: ['moving', 'wheel_interaction'],
      segments: [
        { action: 'moving', start_sec: 0, end_sec: 4 },
        { action: 'wheel_interaction', start_sec: 1, end_sec: 3 },
      ],
      enrichment_object: 'wheel',
      interaction_types: ['ride', 'rotate'],
      activity_intensity: 'high',
    });

    expect(validateGroundTruth(input, 30)).toEqual(input);
  });

  it('rejects playing as a direct human action', () => {
    expect(() =>
      validateGroundTruth(
        validGt({ primary_action: 'playing' as GroundTruthInput['primary_action'] }),
        30,
      ),
    ).toThrow('playing');
  });

  it('rejects segments outside the clip duration', () => {
    expect(() =>
      validateGroundTruth(
        validGt({
          segments: [{ action: 'moving', start_sec: 10, end_sec: 31 }],
        }),
        30,
      ),
    ).toThrow('구간');
  });

  it('requires a segment for every visible observed action', () => {
    expect(() =>
      validateGroundTruth(
        validGt({ observed_actions: ['moving', 'licking'] }),
        30,
      ),
    ).toThrow('각 관찰 행동');
  });
});

describe('workflow helpers', () => {
  const prediction = { id: 'vlm-1', action: 'drinking', confidence: 0.65 };

  it('redacts prediction until an initial GT exists', () => {
    expect(revealPrediction(null, prediction)).toBeNull();
    expect(revealPrediction({ initial_gt: null }, prediction)).toBeNull();
  });

  it('reveals the exact prediction after GT lock', () => {
    expect(revealPrediction({ initial_gt: validGt() }, prediction)).toEqual(
      prediction,
    );
  });

  it('only permits draft to gt_locked to completed transitions', () => {
    expect(nextStage('draft', 'lock_gt')).toBe('gt_locked');
    expect(nextStage('gt_locked', 'complete_vlm_review')).toBe('completed');
    expect(() => nextStage('draft', 'complete_vlm_review')).toThrow('단계');
  });

  it('requires error tags for incorrect VLM reviews', () => {
    expect(() =>
      validateVlmReview({ verdict: 'incorrect', error_tags: [], note: null }),
    ).toThrow('오류 유형');
  });
});

describe('thumbnailKeyForClip', () => {
  it('prefers the explicit thumbnail key', () => {
    expect(
      thumbnailKeyForClip({
        thumbnail_r2_key: 'thumbs/a.jpg',
        r2_key: 'clips/a.mp4',
      }),
    ).toBe('thumbs/a.jpg');
  });

  it('derives jpg next to an mp4 when the DB key is missing', () => {
    expect(
      thumbnailKeyForClip({ thumbnail_r2_key: null, r2_key: 'clips/a.mp4' }),
    ).toBe('clips/a.jpg');
  });

  it('rejects a clip without any R2 key', () => {
    expect(() =>
      thumbnailKeyForClip({ thumbnail_r2_key: null, r2_key: null }),
    ).toThrow('썸네일');
  });
});
