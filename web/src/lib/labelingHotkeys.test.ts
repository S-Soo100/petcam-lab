import { describe, expect, it } from 'vitest';

import { isTypingTarget, mapHotkey } from './labelingHotkeys';

describe('mapHotkey', () => {
  it('O/X·한글 자판·숫자·Enter·Space·N·F 를 매핑한다', () => {
    expect(mapHotkey({ key: 'o' })).toEqual({ kind: 'verdict', verdict: true });
    expect(mapHotkey({ key: 'ㅐ' })).toEqual({ kind: 'verdict', verdict: true });
    expect(mapHotkey({ key: 'X' })).toEqual({ kind: 'verdict', verdict: false });
    expect(mapHotkey({ key: '3' })).toEqual({ kind: 'reason', index: 2 });
    expect(mapHotkey({ key: '6' })).toBeNull();
    expect(mapHotkey({ key: 'Enter' })).toEqual({ kind: 'save' });
    expect(mapHotkey({ key: ' ' })).toEqual({ kind: 'toggle_play' });
    expect(mapHotkey({ key: 'n' })).toEqual({ kind: 'next_motion' });
    expect(mapHotkey({ key: 'f' })).toEqual({ kind: 'toggle_flag' });
    expect(mapHotkey({ key: 'w' })).toEqual({ kind: 'toggle_wheel' });
    expect(mapHotkey({ key: 'ㅈ' })).toEqual({ kind: 'toggle_wheel' });
    expect(mapHotkey({ key: 'D' })).toEqual({ kind: 'toggle_fall' });
    expect(mapHotkey({ key: 'p' })).toEqual({ kind: 'toggle_closeup' });
    expect(mapHotkey({ key: 'q' })).toBeNull();
  });
  it('입력 중이거나 조합키면 무시', () => {
    expect(mapHotkey({ key: 'o', target: { tagName: 'input' } })).toBeNull();
    expect(mapHotkey({ key: 'o', target: { tagName: 'DIV', isContentEditable: true } })).toBeNull();
    expect(mapHotkey({ key: 'o', metaKey: true })).toBeNull();
    expect(mapHotkey({ key: 'o', ctrlKey: true })).toBeNull();
    expect(isTypingTarget({ tagName: 'TEXTAREA' })).toBe(true);
    expect(isTypingTarget({ tagName: 'BUTTON' })).toBe(false);
    expect(isTypingTarget(null)).toBe(false);
  });
});
