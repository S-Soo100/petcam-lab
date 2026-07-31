import { describe, expect, it } from 'vitest';

import { validateBlindSlotPair, type BlindSlotVersionRow } from './_access';

const USER = '11111111-1111-4111-8111-111111111111';
const PEER = '22222222-2222-4222-8222-222222222222';
const GROUP = '33333333-3333-4333-8333-333333333333';
const COHORT = '44444444-4444-4444-8444-444444444444';

function rows(
  comparatorVersion: string,
  cohortKind: 'live' | 'canary' = 'live',
): BlindSlotVersionRow[] {
  return [USER, PEER].map((reviewerId) => ({
    reviewer_id: reviewerId,
    group_id: GROUP,
    activity_day_kst: '2026-08-01',
    submitted_at: null,
    cohort_kind: cohortKind,
    cohort_id: cohortKind === 'canary' ? COHORT : null,
    comparator_version: comparatorVersion,
  }));
}

describe('validateBlindSlotPair', () => {
  it('accepts a uniform live v2 pair and returns the authenticated slot version', () => {
    const result = validateBlindSlotPair(
      rows('motion-blind-live-v2-highlight-soft'),
      USER,
      { cohortKind: 'live', cohortId: null },
    );
    expect(result).toMatchObject({
      groupId: GROUP,
      comparatorVersion: 'motion-blind-live-v2-highlight-soft',
    });
  });

  it('fails closed for an unknown comparator version', () => {
    expect(
      validateBlindSlotPair(rows('unknown'), USER, {
        cohortKind: 'live',
        cohortId: null,
      }),
    ).toBeNull();
  });

  it('fails closed when a canary slot carries v2', () => {
    expect(
      validateBlindSlotPair(
        rows('motion-blind-live-v2-highlight-soft', 'canary'),
        USER,
        { cohortKind: 'canary', cohortId: COHORT },
      ),
    ).toBeNull();
  });

  it('fails closed when the two slot versions differ', () => {
    const mismatched = rows('motion-blind-v1');
    mismatched[1].comparator_version = 'motion-blind-live-v2-highlight-soft';
    expect(
      validateBlindSlotPair(mismatched, USER, {
        cohortKind: 'live',
        cohortId: null,
      }),
    ).toBeNull();
  });
});
