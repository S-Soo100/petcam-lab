import { describe, expect, it } from 'vitest';

import {
  canWriteMotionGt,
  decideMotionDetailPhase,
  motionDecisionListPath,
  parseMotionState,
  resolveLabelingQueueSource,
  type MotionLabelingState,
} from './labelingV3';

// motion_clips 운영 라벨링 v3 순수 계약 테스트(구현계획 Task 2).
// 상태 파서는 client·server 가 공유하는 단일 규칙이라 여기서 고정한다.

describe('parseMotionState', () => {
  it('null/undefined 는 unreviewed 로 접힌다', () => {
    expect(parseMotionState(null)).toBe('unreviewed');
    expect(parseMotionState(undefined)).toBe('unreviewed');
  });

  it('유효 상태는 그대로 통과한다', () => {
    const states: MotionLabelingState[] = ['unreviewed', 'label', 'hold', 'skip'];
    for (const s of states) {
      expect(parseMotionState(s)).toBe(s);
    }
  });

  it('legacy triage 값(quarantine)이나 미지 값은 거부한다', () => {
    expect(() => parseMotionState('quarantine')).toThrow('invalid_motion_state');
    expect(() => parseMotionState('label ')).toThrow('invalid_motion_state');
    expect(() => parseMotionState('LABEL')).toThrow('invalid_motion_state');
    expect(() => parseMotionState('')).toThrow('invalid_motion_state');
  });
});

describe('decideMotionDetailPhase', () => {
  it('세션 없음 + media-ready → gt(작성)', () => {
    expect(decideMotionDetailPhase({ session: null, media_ready: true })).toBe('gt');
  });

  it('gt_locked → review(검수)', () => {
    expect(decideMotionDetailPhase({ session: { stage: 'gt_locked' } })).toBe('review');
  });

  it('completed → complete', () => {
    expect(decideMotionDetailPhase({ session: { stage: 'completed' } })).toBe('complete');
  });

  it('세션 없음 + 재생 불가 → media_blocked', () => {
    expect(decideMotionDetailPhase({ session: null, media_ready: false })).toBe('media_blocked');
  });

  it('세션 있으면 media 상태와 무관하게 review/complete 우선', () => {
    expect(decideMotionDetailPhase({ session: { stage: 'gt_locked' }, media_ready: false })).toBe('review');
    expect(decideMotionDetailPhase({ session: { stage: 'completed' }, media_ready: false })).toBe('complete');
  });
});

// hold/skip 결정이 GT 저장을 조용히 label 로 덮어쓰지 못하게 막는 공유 순수 규칙(설계 §4·§5.1).
// UI·API·DB 가 같은 상태 계약을 쓰므로 여기서 상태→쓰기가능/이동경로를 고정한다.
describe('canWriteMotionGt', () => {
  it('unreviewed/label 에서만 사람 판정(GT) 저장을 허용한다', () => {
    expect(canWriteMotionGt('unreviewed')).toBe(true);
    expect(canWriteMotionGt('label')).toBe(true);
  });

  it('hold/skip 에서는 GT 저장을 막는다(먼저 라벨 대상으로 보내야 함)', () => {
    expect(canWriteMotionGt('hold')).toBe(false);
    expect(canWriteMotionGt('skip')).toBe(false);
  });
});

describe('motionDecisionListPath', () => {
  it('hold/skip 결정 후 각각의 필터 탭 경로를 돌려준다', () => {
    expect(motionDecisionListPath('hold')).toBe('/labeling/motion?state=hold');
    expect(motionDecisionListPath('skip')).toBe('/labeling/motion?state=skip');
  });

  it('label/unreviewed 는 이동 경로가 없다(현재 화면 유지)', () => {
    expect(motionDecisionListPath('label')).toBeNull();
    expect(motionDecisionListPath('unreviewed')).toBeNull();
  });
});

describe('resolveLabelingQueueSource', () => {
  it('motion 만 motion, 나머지는 legacy(안전 기본)', () => {
    expect(resolveLabelingQueueSource('motion')).toBe('motion');
    expect(resolveLabelingQueueSource('legacy')).toBe('legacy');
    expect(resolveLabelingQueueSource(undefined)).toBe('legacy');
    expect(resolveLabelingQueueSource(null)).toBe('legacy');
    expect(resolveLabelingQueueSource('bad')).toBe('legacy');
  });
});
