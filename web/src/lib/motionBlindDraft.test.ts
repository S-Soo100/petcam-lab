import { describe, expect, it } from 'vitest';

import type { GroundTruthInput } from './labelingV2';
import {
  BLIND_DRAFT_VERSION,
  blindDraftKey,
  clearBlindDraft,
  parseBlindDraft,
  readBlindDraft,
  serializeBlindDraft,
  writeBlindDraft,
  type BlindDraftScope,
  type BlindDraftV1,
} from './motionBlindDraft';

function fakeStorage() {
  const map = new Map<string, string>();
  return {
    map,
    getItem: (k: string) => map.get(k) ?? null,
    setItem: (k: string, v: string) => {
      map.set(k, v);
    },
    removeItem: (k: string) => {
      map.delete(k);
    },
  };
}

const SCOPE: BlindDraftScope = {
  userId: 'user-1',
  clipId: 'clip-1',
  cohortKind: 'live',
  cohortId: null,
  comparatorVersion: 'motion-blind-v1',
};

function validGt(endSec = 2): GroundTruthInput {
  return {
    visibility: 'visible',
    primary_action: 'moving',
    observed_actions: ['moving'],
    segments: [{ action: 'moving', start_sec: 0, end_sec: endSec }],
    target: 'none',
    human_confidence: 'certain',
    context_tags: [],
    activity_intensity: null,
    highlight_recommendation: 'exclude',
    enrichment_object: 'none',
    interaction_types: [],
    note: null,
  };
}

function draft(overrides: Partial<BlindDraftV1> = {}): BlindDraftV1 {
  return {
    v: BLIND_DRAFT_VERSION,
    userId: 'user-1',
    clipId: 'clip-1',
    cohortKind: 'live',
    cohortId: null,
    comparatorVersion: 'motion-blind-v1',
    decision: 'label',
    reasonCode: 'behavior_data',
    gt: validGt(),
    selected: ['visibility', 'primary_action'],
    savedAt: '2026-07-24T00:00:00.000Z',
    ...overrides,
  };
}

describe('motionBlindDraft', () => {
  it('round-trips a draft within the same scope and duration', () => {
    const s = fakeStorage();
    const key = blindDraftKey('user-1', 'clip-1', 'live', null, 'motion-blind-v1');
    expect(writeBlindDraft(s, key, draft())).toBe(true);
    const restored = readBlindDraft(s, key, SCOPE, 60);
    expect(restored?.decision).toBe('label');
    expect(restored?.gt.primary_action).toBe('moving');
    expect(restored?.selected).toEqual(['visibility', 'primary_action']);
  });

  it('rejects a draft from a different user', () => {
    expect(parseBlindDraft(serializeBlindDraft(draft({ userId: 'other' })), SCOPE, 60)).toBeNull();
  });

  it('rejects a draft for a different clip', () => {
    expect(parseBlindDraft(serializeBlindDraft(draft({ clipId: 'other' })), SCOPE, 60)).toBeNull();
  });

  it('rejects a draft with a mismatched cohort kind or id', () => {
    // live scope 에 canary 임시본.
    expect(
      parseBlindDraft(serializeBlindDraft(draft({ cohortKind: 'canary', cohortId: 'c1' })), SCOPE, 60),
    ).toBeNull();
    // 같은 canary kind 지만 cohortId 가 다르면 폐기.
    const canaryScope: BlindDraftScope = { ...SCOPE, cohortKind: 'canary', cohortId: 'c1' };
    expect(
      parseBlindDraft(serializeBlindDraft(draft({ cohortKind: 'canary', cohortId: 'c2' })), canaryScope, 60),
    ).toBeNull();
  });

  it('rejects a draft with a wrong version or comparator', () => {
    expect(
      parseBlindDraft(serializeBlindDraft({ ...draft(), v: 2 } as unknown as BlindDraftV1), SCOPE, 60),
    ).toBeNull();
    expect(
      parseBlindDraft(
        serializeBlindDraft({ ...draft(), comparatorVersion: 'motion-blind-v2' } as unknown as BlindDraftV1),
        SCOPE,
        60,
      ),
    ).toBeNull();
  });

  it('rejects and removes a malformed enum/GT/selected draft', () => {
    const s = fakeStorage();
    const key = blindDraftKey('user-1', 'clip-1', 'live', null, 'motion-blind-v1');
    // 잘못된 decision enum.
    s.setItem(key, serializeBlindDraft({ ...draft(), decision: 'bogus' } as unknown as BlindDraftV1));
    expect(readBlindDraft(s, key, SCOPE, 60)).toBeNull();
    expect(s.map.has(key)).toBe(false);
    // 잘못된 GT shape.
    s.setItem(key, serializeBlindDraft({ ...draft(), gt: { visibility: 'nope' } } as unknown as BlindDraftV1));
    expect(readBlindDraft(s, key, SCOPE, 60)).toBeNull();
    expect(s.map.has(key)).toBe(false);
    // 잘못된 selected 필드.
    s.setItem(key, serializeBlindDraft({ ...draft(), selected: ['not_a_field'] } as unknown as BlindDraftV1));
    expect(readBlindDraft(s, key, SCOPE, 60)).toBeNull();
    expect(s.map.has(key)).toBe(false);
  });

  it('rejects and removes a draft whose segment exceeds the current duration', () => {
    const s = fakeStorage();
    const key = blindDraftKey('user-1', 'clip-1', 'live', null, 'motion-blind-v1');
    s.setItem(key, serializeBlindDraft(draft({ gt: validGt(45) })));
    // duration 30 이면 end_sec 45 는 초과 → 폐기 + storage 삭제.
    expect(readBlindDraft(s, key, SCOPE, 30)).toBeNull();
    expect(s.map.has(key)).toBe(false);
    // 같은 임시본이라도 duration 60 이면 복원한다(duration-aware).
    s.setItem(key, serializeBlindDraft(draft({ gt: validGt(45) })));
    expect(readBlindDraft(s, key, SCOPE, 60)?.gt.segments[0].end_sec).toBe(45);
  });

  it('never serializes lease token, peer, VLM, evidence, or R2 key', () => {
    const json = serializeBlindDraft(draft());
    for (const forbidden of ['lease_token', 'leaseToken', 'peer', 'vlm', 'evidence', 'r2_key']) {
      expect(json).not.toContain(forbidden);
    }
  });

  it('clearBlindDraft removes only the matching key', () => {
    const s = fakeStorage();
    const key = blindDraftKey('user-1', 'clip-1', 'live', null, 'motion-blind-v1');
    const other = blindDraftKey('user-1', 'clip-2', 'live', null, 'motion-blind-v1');
    s.setItem(key, serializeBlindDraft(draft()));
    s.setItem(other, serializeBlindDraft(draft({ clipId: 'clip-2' })));
    clearBlindDraft(s, key);
    expect(s.map.has(key)).toBe(false);
    expect(s.map.has(other)).toBe(true);
  });
});
