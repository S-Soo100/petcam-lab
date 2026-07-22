import { describe, expect, it } from 'vitest';

import { parseMotionState, type MotionLabelingState } from './labelingV3';

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
