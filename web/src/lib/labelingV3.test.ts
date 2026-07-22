import { describe, expect, it } from 'vitest';

import {
  canWriteMotionGt,
  decideMotionDetailPhase,
  motionUndoDecision,
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

// 결정 취소(undo)는 직전 상태로 되돌린다. 직전이 unreviewed 면 분류 자체를 제거(reset)하고,
// 나머지는 그 상태로 다시 전환한다(설계 §7.2). 강제 탭 이동은 없앴다(연속 검수 흐름).
describe('motionUndoDecision', () => {
  it('직전이 unreviewed 면 reset(분류 제거)', () => {
    expect(motionUndoDecision('unreviewed')).toBe('reset');
  });

  it('직전이 label/hold/skip 이면 그 상태로 되돌린다', () => {
    expect(motionUndoDecision('label')).toBe('label');
    expect(motionUndoDecision('hold')).toBe('hold');
    expect(motionUndoDecision('skip')).toBe('skip');
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
