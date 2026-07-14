import { describe, expect, it } from 'vitest';

import {
  clearDraft,
  draftKey,
  parseGtDraft,
  parseReviewDraft,
  readGtDraft,
  readReviewDraft,
  serializeDraft,
  writeDraft,
  type DraftStorage,
  type GtDraft,
  type ReviewDraft,
} from './labelingDraft';
import type { GroundTruthInput, VlmReviewInput } from './labelingV2';

function gt(overrides: Partial<GroundTruthInput> = {}): GroundTruthInput {
  return {
    visibility: 'visible', primary_action: 'moving', observed_actions: ['moving'],
    segments: [{ action: 'moving', start_sec: 0, end_sec: 4 }], target: 'none',
    human_confidence: 'certain', context_tags: [], activity_intensity: null,
    highlight_recommendation: 'include', enrichment_object: 'none', interaction_types: [],
    note: null, ...overrides,
  };
}

function gtDraft(userId: string, overrides: Partial<GtDraft> = {}): GtDraft {
  return {
    v: 2, userId, phase: 'gt', gt: gt(), selected: ['visibility', 'primary_action'],
    savedAt: '2026-07-14T00:00:00Z', ...overrides,
  };
}

function review(overrides: Partial<VlmReviewInput> = {}): VlmReviewInput {
  return { verdict: 'correct', error_tags: [], note: null, ...overrides };
}

function reviewDraft(userId: string, overrides: Partial<ReviewDraft> = {}): ReviewDraft {
  return {
    v: 2, userId, phase: 'review', review: review(), savedAt: '2026-07-14T00:00:00Z', ...overrides,
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

describe('draftKey (하드닝 §3 — user/set/lesson/phase 격리)', () => {
  it('user·scope·phase 로 격리한다', () => {
    // 다른 user
    expect(draftKey('u1', 'tutorial:setA:3', 'gt')).not.toBe(draftKey('u2', 'tutorial:setA:3', 'gt'));
    // 다른 lesson position
    expect(draftKey('u1', 'tutorial:setA:3', 'gt')).not.toBe(draftKey('u1', 'tutorial:setA:4', 'gt'));
    // 다른 tutorial set(v1↔v2) — 같은 clip/position 이라도 set identity 로 분리
    expect(draftKey('u1', 'tutorial:setV1:3', 'gt')).not.toBe(draftKey('u1', 'tutorial:setV2:3', 'gt'));
    // gt ↔ review 단계 분리
    expect(draftKey('u1', 'tutorial:setA:3', 'gt')).not.toBe(draftKey('u1', 'tutorial:setA:3', 'review'));
    expect(draftKey('u1', 'clip:abc', 'gt')).toContain('u1');
  });

  it('v1 임시본은 v2 에서 절대 복원되지 않는다', () => {
    const v1Key = draftKey('u1', 'tutorial:setV1:3', 'gt');
    const storage = fakeStorage({ [v1Key]: serializeDraft(gtDraft('u1')) });
    // v2 는 다른 set identity 키를 읽으므로 v1 임시본을 못 본다.
    const v2Key = draftKey('u1', 'tutorial:setV2:3', 'gt');
    expect(readGtDraft(storage, v2Key, 'u1')).toBeNull();
    // 원래 v1 키로는 정상 복원(격리는 키 분리로 달성).
    expect(readGtDraft(storage, v1Key, 'u1')?.phase).toBe('gt');
  });
});

describe('parseGtDraft / parseReviewDraft — 봉투 검증', () => {
  it('같은 user 의 gt 임시본을 왕복한다', () => {
    const d = gtDraft('u1');
    expect(parseGtDraft(serializeDraft(d), 'u1')).toEqual(d);
  });

  it('같은 user 의 review 임시본을 왕복한다', () => {
    const d = reviewDraft('u1');
    expect(parseReviewDraft(serializeDraft(d), 'u1')).toEqual(d);
  });

  it('다른 user 임시본은 복원하지 않는다 (§9.3)', () => {
    expect(parseGtDraft(serializeDraft(gtDraft('u1')), 'u2')).toBeNull();
    expect(parseReviewDraft(serializeDraft(reviewDraft('u1')), 'u2')).toBeNull();
  });

  it('버전 불일치는 폐기한다', () => {
    const raw = JSON.stringify({ ...gtDraft('u1'), v: 99 });
    expect(parseGtDraft(raw, 'u1')).toBeNull();
  });

  it('phase 불일치는 폐기한다 (gt 파서는 review 임시본을 안 읽는다)', () => {
    expect(parseGtDraft(serializeDraft(reviewDraft('u1')), 'u1')).toBeNull();
    expect(parseReviewDraft(serializeDraft(gtDraft('u1')), 'u1')).toBeNull();
  });

  it('비-JSON / null 을 조용히 폐기한다', () => {
    expect(parseGtDraft('{not json', 'u1')).toBeNull();
    expect(parseGtDraft('null', 'u1')).toBeNull();
    expect(parseGtDraft(null, 'u1')).toBeNull();
  });
});

describe('구조 검증 — 손상/변조 임시본 폐기 (하드닝 §5)', () => {
  it('정상 미완성 gt draft 는 복원한다', () => {
    // 관찰 없음·segment 없음 — 구조는 유효(제출 의미 검증과 별개).
    const d = gtDraft('u1', { gt: gt({ observed_actions: [], segments: [] }), selected: [] });
    expect(parseGtDraft(serializeDraft(d), 'u1')).toEqual(d);
  });

  it('잘못된 enum 은 폐기한다', () => {
    const raw = JSON.stringify(gtDraft('u1', { gt: { ...gt(), visibility: 'zzz' } as never }));
    expect(parseGtDraft(raw, 'u1')).toBeNull();
  });

  it('segments 가 문자열이면 폐기한다', () => {
    const raw = JSON.stringify({ ...gtDraft('u1'), gt: { ...gt(), segments: 'oops' } });
    expect(parseGtDraft(raw, 'u1')).toBeNull();
  });

  it('NaN/Infinity 로 직렬화된 잘못된 숫자는 폐기한다', () => {
    // JSON.stringify(NaN) === 'null' → 숫자 아님 → 구조 검증 실패.
    const raw = JSON.stringify({
      ...gtDraft('u1'),
      gt: { ...gt(), segments: [{ action: 'moving', start_sec: NaN, end_sec: 4 }] },
    });
    expect(raw).toContain('null'); // NaN 이 null 로 직렬화됨을 확인
    expect(parseGtDraft(raw, 'u1')).toBeNull();
  });

  it('review 형식 오류는 폐기한다', () => {
    const raw = JSON.stringify({ ...reviewDraft('u1'), review: { verdict: 'bogus', error_tags: [], note: null } });
    expect(parseReviewDraft(raw, 'u1')).toBeNull();
  });

  it('selected 가 배열이 아니거나 잘못된 필드면 폐기한다', () => {
    expect(parseGtDraft(JSON.stringify({ ...gtDraft('u1'), selected: 'nope' }), 'u1')).toBeNull();
    expect(parseGtDraft(JSON.stringify({ ...gtDraft('u1'), selected: ['bogus'] }), 'u1')).toBeNull();
  });
});

describe('readGtDraft / readReviewDraft — 손상 임시본 자동 삭제', () => {
  it('같은 user/key gt 임시본을 반환한다', () => {
    const key = draftKey('u1', 'clip:c1', 'gt');
    const storage = fakeStorage({ [key]: serializeDraft(gtDraft('u1')) });
    expect(readGtDraft(storage, key, 'u1')?.userId).toBe('u1');
  });

  it('손상/타 사용자 임시본은 반환하지 않고 storage 에서도 삭제한다 (하드닝 §5)', () => {
    const key = draftKey('u1', 'clip:c1', 'gt');
    const storage = fakeStorage({ [key]: serializeDraft(gtDraft('other-user')) });
    expect(readGtDraft(storage, key, 'u1')).toBeNull();
    expect(storage.map.has(key)).toBe(false);
  });

  it('손상된 review 임시본도 삭제한다', () => {
    const key = draftKey('u1', 'clip:c1', 'review');
    const storage = fakeStorage({ [key]: '{corrupt' });
    expect(readReviewDraft(storage, key, 'u1')).toBeNull();
    expect(storage.map.has(key)).toBe(false);
  });
});

describe('writeDraft / clearDraft — gt/review 단계별 독립 삭제 (하드닝 §4)', () => {
  it('gt 저장 후 gt 임시본만 삭제하고 review 임시본은 보존한다', () => {
    const gtKey = draftKey('u1', 'tutorial:setA:3', 'gt');
    const reviewKey = draftKey('u1', 'tutorial:setA:3', 'review');
    const storage = fakeStorage();
    writeDraft(storage, gtKey, gtDraft('u1'));
    writeDraft(storage, reviewKey, reviewDraft('u1'));
    // 사람 판정 저장 성공 → gt 임시본만 삭제.
    clearDraft(storage, gtKey);
    expect(storage.map.has(gtKey)).toBe(false);
    expect(storage.map.has(reviewKey)).toBe(true);
  });

  it('review 제출 후 다른 lesson 의 임시본을 삭제하지 않는다', () => {
    const thisReview = draftKey('u1', 'tutorial:setA:3', 'review');
    const otherLesson = draftKey('u1', 'tutorial:setA:4', 'review');
    const storage = fakeStorage();
    writeDraft(storage, thisReview, reviewDraft('u1'));
    writeDraft(storage, otherLesson, reviewDraft('u1'));
    clearDraft(storage, thisReview);
    expect(storage.map.has(thisReview)).toBe(false);
    expect(storage.map.has(otherLesson)).toBe(true);
  });

  it('storage 예외(quota 등)면 실패를 보고한다', () => {
    const throwing: DraftStorage = {
      getItem: () => null,
      setItem: () => {
        throw new Error('quota');
      },
      removeItem: () => {},
    };
    expect(writeDraft(throwing, 'k', gtDraft('u1'))).toBe(false);
  });
});
