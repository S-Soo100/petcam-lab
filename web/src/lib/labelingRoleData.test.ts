import { describe, expect, it } from 'vitest';

import {
  collapseFinalStatus,
  finalStatusCopy,
  labelSourceCopy,
  labelStateCopy,
} from './labelingRoleData';

describe('labelSourceCopy — 라벨 출처 표시(설계 §6)', () => {
  it('새 합의와 기존 라벨을 구분한다', () => {
    expect(labelSourceCopy('blind_consensus')).toBe('이중 확인 완료');
    expect(labelSourceCopy('owner_legacy')).toBe('기존 Owner 라벨');
    expect(labelSourceCopy('single_legacy')).toBe('기존 단일 라벨');
    expect(labelSourceCopy('none')).toBe('라벨 없음');
  });
});

describe('labelStateCopy — 확정 전 상태 은닉(설계 §6.1)', () => {
  it('awaiting/owner_review 는 상태 문구만', () => {
    expect(labelStateCopy('awaiting')).toBe('라벨 확정 중');
    expect(labelStateCopy('owner_review')).toBe('Owner 검수 중');
    expect(labelStateCopy('final')).toBe('최종 라벨');
    expect(labelStateCopy('unlabeled')).toBe('미분류');
  });

  it('re_review 는 정확히 "라벨 재검수 중"(review-fix P0-1, canary 편입 시 과거 GT 은닉)', () => {
    expect(labelStateCopy('re_review')).toBe('라벨 재검수 중');
  });
});

describe('collapseFinalStatus — 라벨러 안전 2단계(설계 §5.2)', () => {
  it('agreed/owner_resolved 만 확정, 나머지는 검수 중', () => {
    expect(collapseFinalStatus('agreed')).toBe('confirmed');
    expect(collapseFinalStatus('owner_resolved')).toBe('confirmed');
    // conflict 도 in_review 로 접어 불일치 발생 여부를 숨긴다(blind).
    expect(collapseFinalStatus('conflict')).toBe('in_review');
    expect(collapseFinalStatus('awaiting')).toBe('in_review');
    expect(collapseFinalStatus(null)).toBe('in_review');
    expect(collapseFinalStatus(undefined)).toBe('in_review');
  });

  it('finalStatusCopy 는 확정됨/검수 중', () => {
    expect(finalStatusCopy('confirmed')).toBe('확정됨');
    expect(finalStatusCopy('in_review')).toBe('검수 중');
  });
});
