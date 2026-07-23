import { describe, it, expect } from 'vitest';
import type { GroundTruthInput } from './labelingV2';
import {
  BLIND_COMPARATOR_VERSION,
  BLIND_DECISION_COPY,
  activityDayBounds,
  currentActivityDay,
  compareBlindSubmissions,
  validateBlindSubmissionInput,
  canonicalSubmissionPair,
  type BlindSubmissionInput,
} from './motionBlindReview';

// 라벨 GT 는 폼이 항상 비-null 계약을 채운다(§6.1). 테스트에선 유효한 기준 GT 를
// 만들고 필요한 필드만 override 한다.
function baseGt(overrides: Partial<GroundTruthInput> = {}): GroundTruthInput {
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
  // note 는 GT 안에 담아 "GT note 는 비교 제외 + 원문 보존"을 정확히 검증한다.
  const gt = baseGt(overrides);
  return {
    decision: 'label',
    initial_gt: gt,
    note: gt.note,
    reason_code: 'behavior_data',
  };
}

function exclude(
  overrides: { reason_code?: BlindSubmissionInput['reason_code']; note?: string | null } = {},
): BlindSubmissionInput {
  return {
    decision: 'exclude',
    initial_gt: null,
    note: overrides.note ?? null,
    reason_code: overrides.reason_code ?? 'gecko_absent',
  };
}

function hold(overrides: { note?: string | null } = {}): BlindSubmissionInput {
  return {
    decision: 'hold',
    initial_gt: null,
    note: overrides.note ?? null,
    reason_code: 'ambiguous',
  };
}

describe('activity day', () => {
  it('computes KST 07:00~07:00 bounds', () => {
    expect(activityDayBounds('2026-07-22')).toEqual({
      from: '2026-07-21T22:00:00.000Z',
      to: '2026-07-22T22:00:00.000Z',
    });
  });

  it('maps a UTC instant to its KST activity day', () => {
    expect(currentActivityDay(new Date('2026-07-23T00:30:00.000Z'))).toBe('2026-07-23');
  });

  it('honors the 07:00 KST cutoff', () => {
    // 2026-07-22T21:59Z = 2026-07-23 06:59 KST -> still 2026-07-22 activity day
    expect(currentActivityDay(new Date('2026-07-22T21:59:00.000Z'))).toBe('2026-07-22');
    // 2026-07-22T22:00Z = 2026-07-23 07:00 KST -> 2026-07-23 activity day
    expect(currentActivityDay(new Date('2026-07-22T22:00:00.000Z'))).toBe('2026-07-23');
  });

  it('rejects a malformed day string', () => {
    expect(() => activityDayBounds('2026-7-2')).toThrow();
    expect(() => activityDayBounds('not-a-date')).toThrow();
  });
});

describe('decision copy', () => {
  it('exposes user-facing copy', () => {
    expect(BLIND_DECISION_COPY.exclude.description).toContain('촬영');
    expect(BLIND_DECISION_COPY.hold.description).not.toContain('관리자 확인');
    expect(BLIND_DECISION_COPY.label.title).toBe('라벨링하기');
    expect(BLIND_DECISION_COPY.hold.title).toBe('보류하기');
    expect(BLIND_DECISION_COPY.exclude.title).toBe('제외하기');
  });
});

describe('comparator version', () => {
  it('is motion-blind-v1', () => {
    expect(BLIND_COMPARATOR_VERSION).toBe('motion-blind-v1');
  });
});

describe('compareBlindSubmissions — non-label decisions', () => {
  it('agrees when both exclude regardless of reason code', () => {
    const c = compareBlindSubmissions(
      exclude({ reason_code: 'gecko_absent' }),
      exclude({ reason_code: 'media_error' }),
    );
    expect(c.status).toBe('agreed');
    expect(c.final_decision).toBe('exclude');
    expect(c.final_gt).toBeNull();
    expect(c.comparator_version).toBe('motion-blind-v1');
  });

  it('agrees when both hold', () => {
    const c = compareBlindSubmissions(hold(), hold());
    expect(c.status).toBe('agreed');
    expect(c.final_decision).toBe('hold');
  });

  it('conflicts when decisions differ', () => {
    expect(compareBlindSubmissions(exclude(), hold()).status).toBe('conflict');
    expect(compareBlindSubmissions(exclude(), label()).status).toBe('conflict');
    expect(compareBlindSubmissions(hold(), label()).status).toBe('conflict');
  });

  it('marks decision as the differing field on decision mismatch', () => {
    expect(compareBlindSubmissions(exclude(), hold())).toMatchObject({
      status: 'conflict',
      differing_fields: ['decision'],
      final_decision: null,
      final_gt: null,
    });
  });
});

describe('compareBlindSubmissions — label agreement', () => {
  it('ignores free-form note differences', () => {
    const c = compareBlindSubmissions(label({ note: 'A' }), label({ note: 'B' }));
    expect(c.status).toBe('agreed');
    expect(c.final_decision).toBe('label');
    // 원문 note 는 보존한다(비교에서만 제외).
    expect(c.final_gt?.note).toBe('A');
  });

  it('treats duplicated/unordered set fields as equal', () => {
    const c = compareBlindSubmissions(
      label({ observed_actions: ['moving', 'licking', 'moving'] }),
      label({ observed_actions: ['licking', 'moving'] }),
    );
    expect(c.status).toBe('agreed');
  });

  it('treats unordered context_tags and interaction_types as sets', () => {
    expect(
      compareBlindSubmissions(
        label({ context_tags: ['ir', 'blur'] }),
        label({ context_tags: ['blur', 'ir'] }),
      ).status,
    ).toBe('agreed');
    expect(
      compareBlindSubmissions(
        label({ interaction_types: ['ride', 'push'] }),
        label({ interaction_types: ['push', 'ride'] }),
      ).status,
    ).toBe('agreed');
  });

  it('treats segment boundaries within 500ms as equal', () => {
    const c = compareBlindSubmissions(
      label({ segments: [{ action: 'moving', start_sec: 1, end_sec: 2 }] }),
      label({ segments: [{ action: 'moving', start_sec: 1.5, end_sec: 2.5 }] }),
    );
    expect(c.status).toBe('agreed');
  });
});

describe('compareBlindSubmissions — label conflict', () => {
  it('conflicts when a segment boundary drifts past 500ms', () => {
    expect(
      compareBlindSubmissions(
        label({ segments: [{ action: 'moving', start_sec: 1, end_sec: 2 }] }),
        label({ segments: [{ action: 'moving', start_sec: 1.501, end_sec: 2 }] }),
      ),
    ).toMatchObject({ status: 'conflict', differing_fields: ['segments'] });
  });

  it('conflicts on scalar mismatch', () => {
    expect(
      compareBlindSubmissions(
        label({ primary_action: 'moving' }),
        label({ primary_action: 'drinking' }),
      ),
    ).toMatchObject({ status: 'conflict', differing_fields: ['primary_action'] });
  });

  it('conflicts when segment count differs', () => {
    const c = compareBlindSubmissions(
      label({ segments: [{ action: 'moving', start_sec: 0, end_sec: 1 }] }),
      label({
        segments: [
          { action: 'moving', start_sec: 0, end_sec: 1 },
          { action: 'static', start_sec: 1, end_sec: 2 },
        ],
      }),
    );
    expect(c.status).toBe('conflict');
    expect(c.differing_fields).toContain('segments');
  });

  it('conflicts when a corresponding segment action differs', () => {
    const c = compareBlindSubmissions(
      label({ segments: [{ action: 'moving', start_sec: 0, end_sec: 1 }] }),
      label({ segments: [{ action: 'static', start_sec: 0, end_sec: 1 }] }),
    );
    expect(c.status).toBe('conflict');
    expect(c.differing_fields).toContain('segments');
  });

  it('lists differing fields in fixed GroundTruthInput order', () => {
    const c = compareBlindSubmissions(
      label({ primary_action: 'moving', target: 'none' }),
      label({ primary_action: 'drinking', target: 'water' }),
    );
    expect(c.status).toBe('conflict');
    expect(c.differing_fields).toEqual(['primary_action', 'target']);
  });
});

describe('validateBlindSubmissionInput', () => {
  it('rejects label without a valid initial_gt', () => {
    expect(() =>
      validateBlindSubmissionInput({
        decision: 'label',
        initial_gt: null,
        note: null,
        reason_code: 'behavior_data',
      }),
    ).toThrow('label_requires_valid_initial_gt');
  });

  it('rejects label with a malformed initial_gt', () => {
    expect(() =>
      validateBlindSubmissionInput({
        decision: 'label',
        // @ts-expect-error malformed on purpose
        initial_gt: { visibility: 'nope' },
        note: null,
        reason_code: 'behavior_data',
      }),
    ).toThrow('label_requires_valid_initial_gt');
  });

  it('rejects exclude/hold that carries an initial_gt', () => {
    expect(() =>
      validateBlindSubmissionInput({
        decision: 'exclude',
        initial_gt: baseGt(),
        note: null,
        reason_code: 'gecko_absent',
      }),
    ).toThrow('non_label_forbids_initial_gt');
  });

  it('comparator throws on malformed input before comparing', () => {
    expect(() =>
      compareBlindSubmissions(
        {
          decision: 'label',
          initial_gt: null,
          note: null,
          reason_code: 'behavior_data',
        },
        label(),
      ),
    ).toThrow('label_requires_valid_initial_gt');
  });
});

describe('canonicalSubmissionPair', () => {
  it('orders the pair by submission id regardless of arg order', () => {
    const a = { id: 'aaaa', digest: 'da' };
    const b = { id: 'bbbb', digest: 'db' };
    expect(canonicalSubmissionPair(a, b)).toEqual([a, b]);
    expect(canonicalSubmissionPair(b, a)).toEqual([a, b]);
  });
});

describe('input type safety', () => {
  it('does not admit prediction/current GT fields', () => {
    const input: BlindSubmissionInput = {
      decision: 'label',
      initial_gt: baseGt(),
      note: null,
      reason_code: 'behavior_data',
      // @ts-expect-error prediction/current GT must never enter the blind input
      current_gt: baseGt(),
    };
    expect(input.decision).toBe('label');
  });
});
