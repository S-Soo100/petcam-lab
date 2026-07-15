// 라벨링 영역 경로 접근 판정 — layout.tsx 에서 추출한 순수 로직(테스트 대상).
//
// categorize: pathname → 접근 카테고리. redirectTarget: (세션/상태/카테고리) → 보낼 곳 or null.
// owner 전용 경로(팀원 관리, 격리함)는 'owner' 카테고리로 묶여 labeler 는 자동으로 /labeling 로
// 튕긴다(설계 §7 owner-only, 라벨러 URL 직접 입력 차단).

import type { LabelingAccessInfo } from './labelingApi';

export type RouteCategory =
  | 'public'
  | 'apply'
  | 'pending'
  | 'owner'
  | 'tutorial'
  | 'work';

export function categorize(pathname: string): RouteCategory {
  if (
    pathname.startsWith('/labeling/login') ||
    pathname.startsWith('/labeling/signup')
  ) {
    return 'public';
  }
  if (pathname === '/labeling/apply') return 'apply';
  if (pathname === '/labeling/pending') return 'pending';
  if (pathname.startsWith('/labeling/team')) return 'owner';
  // 격리함은 owner 전용(설계 §7). team 과 같은 카테고리로 묶어 labeler 를 차단한다.
  if (pathname.startsWith('/labeling/quarantine')) return 'owner';
  if (pathname.startsWith('/labeling/tutorial')) return 'tutorial';
  return 'work'; // 큐, 단건 상세, 내 라벨, 라우터 리뷰
}

// 현재 경로가 접근 상태에 맞으면 null, 아니면 보내야 할 목적지.
// owner/labeler 는 apply·pending 에서 자동 이탈, pending/rejected 는 대기 화면,
// unregistered 는 신청 화면으로 정렬한다(§5).
export function redirectTarget(
  hasSession: boolean,
  status: LabelingAccessInfo['status'] | null,
  cat: RouteCategory,
  tutorialRequired: boolean,
): string | null {
  // 공개 페이지(login/signup)는 로그인 여부와 무관하게 항상 렌더 — 페이지가 스스로 라우팅한다.
  if (cat === 'public') return null;
  if (!hasSession) return '/labeling/login';
  switch (status) {
    case 'owner':
      // owner 는 튜토리얼도 preview 가능. 면제이므로 work 로 튕기지 않는다.
      return cat === 'work' || cat === 'owner' || cat === 'tutorial' ? null : '/labeling';
    case 'labeler':
      // 튜토리얼 미완료(required) labeler 는 본 큐 대신 튜토리얼로(설계 §8).
      // owner 카테고리(팀원 관리·격리함)는 labeler 접근 불가 → /labeling.
      if (cat === 'tutorial') return null;
      if (cat === 'work') return tutorialRequired ? '/labeling/tutorial' : null;
      return '/labeling';
    case 'pending':
    case 'rejected':
      return cat === 'pending' ? null : '/labeling/pending';
    case 'unregistered':
      return cat === 'apply' ? null : '/labeling/apply';
    default:
      return null; // 상태 미확정 — 상위 로딩 처리
  }
}
