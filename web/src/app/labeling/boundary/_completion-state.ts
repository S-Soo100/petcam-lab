import type { BoundaryWorkspace } from '@/lib/rbaBoundaryServer';

type ReviewerRole = BoundaryWorkspace['reviewer_role'];

export function boundaryCompletionState(
  reviewerRole: ReviewerRole,
  adjudicationReady: boolean,
) {
  if (reviewerRole === 'owner' && adjudicationReady) {
    return {
      canOpenConflicts: true,
      title: '두 사람의 이어짐 확인이 모두 끝났어.',
      description: '이제 서로 달랐던 판정만 최종 결정하면 돼.',
    } as const;
  }
  if (reviewerRole === 'owner') {
    return {
      canOpenConflicts: false,
      title: '내 이어짐 확인은 끝났어.',
      description: '상대 검수가 끝나면 불일치 해결이 열려.',
    } as const;
  }
  return {
    canOpenConflicts: false,
    title: '내 이어짐 확인은 끝났어.',
    description: 'Owner가 검수를 마칠 때까지 기다리면 돼.',
  } as const;
}
