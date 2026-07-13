import { describe, expect, it } from 'vitest';

import {
  clearDraft,
  draftKey,
  parseDraft,
  readDraft,
  serializeDraft,
  writeDraft,
  type DraftStorage,
  type LabelingDraft,
} from './labelingDraft';
import type { GroundTruthInput } from './labelingV2';

function gt(overrides: Partial<GroundTruthInput> = {}): GroundTruthInput {
  return {
    visibility: 'visible', primary_action: 'moving', observed_actions: ['moving'],
    segments: [{ action: 'moving', start_sec: 0, end_sec: 4 }], target: 'none',
    human_confidence: 'certain', context_tags: [], activity_intensity: null,
    highlight_recommendation: 'include', enrichment_object: 'none', interaction_types: [],
    note: null, ...overrides,
  };
}

function draft(userId: string, overrides: Partial<LabelingDraft> = {}): LabelingDraft {
  return {
    v: 1, userId, gt: gt(), selected: ['visibility', 'primary_action'],
    review: null, savedAt: '2026-07-14T00:00:00Z', ...overrides,
  };
}

// 메모리 기반 fake sessionStorage.
function fakeStorage(seed: Record<string, string> = {}): DraftStorage & { map: Map<string, string> } {
  const map = new Map(Object.entries(seed));
  return {
    map,
    getItem: (k) => (map.has(k) ? (map.get(k) as string) : null),
    setItem: (k, v) => void map.set(k, v),
    removeItem: (k) => void map.delete(k),
  };
}

describe('draftKey', () => {
  it('isolates by user and scope', () => {
    expect(draftKey('u1', 'tutorial:c1:3')).not.toBe(draftKey('u2', 'tutorial:c1:3'));
    expect(draftKey('u1', 'tutorial:c1:3')).not.toBe(draftKey('u1', 'tutorial:c1:4'));
    expect(draftKey('u1', 'clip:abc')).toContain('u1');
  });
});

describe('serializeDraft / parseDraft', () => {
  it('round-trips a draft for the same user', () => {
    const d = draft('u1');
    expect(parseDraft(serializeDraft(d), 'u1')).toEqual(d);
  });

  it('never restores another user draft (§9.3)', () => {
    expect(parseDraft(serializeDraft(draft('u1')), 'u2')).toBeNull();
  });

  it('rejects a mismatched version', () => {
    const raw = JSON.stringify({ ...draft('u1'), v: 99 });
    expect(parseDraft(raw, 'u1')).toBeNull();
  });

  it('rejects malformed / non-JSON silently', () => {
    expect(parseDraft('{not json', 'u1')).toBeNull();
    expect(parseDraft('null', 'u1')).toBeNull();
    expect(parseDraft(JSON.stringify({ v: 1, userId: 'u1' }), 'u1')).toBeNull(); // gt/selected 누락
    expect(parseDraft(null, 'u1')).toBeNull();
  });
});

describe('readDraft', () => {
  it('returns the stored draft for the same user/key', () => {
    const key = draftKey('u1', 'clip:c1');
    const storage = fakeStorage({ [key]: serializeDraft(draft('u1')) });
    expect(readDraft(storage, key, 'u1')?.userId).toBe('u1');
  });

  it('drops and clears a corrupt/foreign draft', () => {
    const key = draftKey('u1', 'clip:c1');
    const storage = fakeStorage({ [key]: serializeDraft(draft('other-user')) });
    expect(readDraft(storage, key, 'u1')).toBeNull();
    // 손상/타 사용자 임시본은 제거된다.
    expect(storage.map.has(key)).toBe(false);
  });
});

describe('writeDraft / clearDraft', () => {
  it('writes then clears by key', () => {
    const key = draftKey('u1', 'clip:c1');
    const storage = fakeStorage();
    expect(writeDraft(storage, key, draft('u1'))).toBe(true);
    expect(storage.map.has(key)).toBe(true);
    clearDraft(storage, key);
    expect(storage.map.has(key)).toBe(false);
  });

  it('reports failure when storage throws (quota etc.)', () => {
    const throwing: DraftStorage = {
      getItem: () => null,
      setItem: () => {
        throw new Error('quota');
      },
      removeItem: () => {},
    };
    expect(writeDraft(throwing, 'k', draft('u1'))).toBe(false);
  });
});
