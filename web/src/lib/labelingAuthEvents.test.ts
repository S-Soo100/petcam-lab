import { describe, expect, it } from 'vitest';

import { decideAuthTransition } from './labelingAuthEvents';

describe('decideAuthTransition (§9.2)', () => {
  it('keeps child + access on TOKEN_REFRESHED for the same user', () => {
    // 근본 원인 회귀: 창 비활성/복귀 시 토큰 갱신이 입력을 초기화하면 안 된다.
    expect(decideAuthTransition('TOKEN_REFRESHED', 'u1', 'u1')).toBe('keep');
  });

  it('rechecks TOKEN_REFRESHED if the user somehow differs', () => {
    expect(decideAuthTransition('TOKEN_REFRESHED', 'u1', 'u2')).toBe('recheck');
  });

  it('keeps a same-user SIGNED_IN (tab refocus) but rechecks a changed user', () => {
    expect(decideAuthTransition('SIGNED_IN', 'u1', 'u1')).toBe('keep');
    expect(decideAuthTransition('SIGNED_IN', 'u1', 'u2')).toBe('recheck');
    // 첫 로그인(prev 없음)은 재확인.
    expect(decideAuthTransition('SIGNED_IN', null, 'u1')).toBe('recheck');
  });

  it('discards on SIGNED_OUT or a null next session', () => {
    expect(decideAuthTransition('SIGNED_OUT', 'u1', null)).toBe('discard');
    expect(decideAuthTransition('TOKEN_REFRESHED', 'u1', null)).toBe('discard');
    expect(decideAuthTransition('SIGNED_IN', 'u1', null)).toBe('discard');
  });

  it('rechecks on USER_UPDATED and unknown events', () => {
    expect(decideAuthTransition('USER_UPDATED', 'u1', 'u1')).toBe('recheck');
    expect(decideAuthTransition('SOMETHING_NEW', 'u1', 'u1')).toBe('recheck');
  });

  it('keeps INITIAL_SESSION for the same user (getSession already checked)', () => {
    expect(decideAuthTransition('INITIAL_SESSION', 'u1', 'u1')).toBe('keep');
    expect(decideAuthTransition('INITIAL_SESSION', null, 'u1')).toBe('recheck');
  });
});
