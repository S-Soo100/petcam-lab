import { describe, expect, it } from 'vitest';

import { createRequestGeneration } from './requestGeneration';

describe('createRequestGeneration', () => {
  it('starts at 0 and bumps on next()', () => {
    const g = createRequestGeneration();
    expect(g.current()).toBe(0);
    expect(g.next()).toBe(1);
    expect(g.next()).toBe(2);
    expect(g.current()).toBe(2);
  });

  it('only the latest generation is current', () => {
    const g = createRequestGeneration();
    const first = g.next();
    expect(g.isCurrent(first)).toBe(true);
    const second = g.next();
    // 새 요청이 시작되면 이전 세대는 stale.
    expect(g.isCurrent(first)).toBe(false);
    expect(g.isCurrent(second)).toBe(true);
  });

  it('a late response from an old generation is rejected while a newer one is in flight', () => {
    // 시나리오: A 요청 → B 요청 → A 응답 도착. A 는 무시되어야 한다.
    const g = createRequestGeneration();
    const genA = g.next(); // A 시작
    const genB = g.next(); // B 시작(같은 대상 전환)
    // A 응답이 늦게 도착:
    expect(g.isCurrent(genA)).toBe(false); // → setState 건너뜀
    // B 응답:
    expect(g.isCurrent(genB)).toBe(true); // → 반영
  });
});
