import { describe, expect, it } from 'vitest';

import { boundaryCompletionState } from './_completion-state';

describe('boundary completion state', () => {
  it('Owner 개인 완료만으로 경계 해결을 열지 않는다', () => {
    expect(boundaryCompletionState('owner', false)).toEqual({
      canOpenConflicts: false,
      title: '내 이어짐 확인은 끝났어.',
      description: '상대 검수가 끝나면 불일치 해결이 열려.',
    });
  });

  it('두 사람 전체 완료가 확인된 뒤에만 경계 해결을 연다', () => {
    expect(boundaryCompletionState('owner', true)).toEqual({
      canOpenConflicts: true,
      title: '두 사람의 이어짐 확인이 모두 끝났어.',
      description: '이제 서로 달랐던 판정만 최종 결정하면 돼.',
    });
  });

  it('peer에게는 conflict 진입을 절대 열지 않는다', () => {
    expect(boundaryCompletionState('peer', true).canOpenConflicts).toBe(false);
  });
});
