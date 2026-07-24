// 라벨링 영역 경로 접근 판정 — layout.tsx 에서 추출한 순수 로직(테스트 대상).
//
// categorize: pathname → 접근 카테고리. redirectTarget: (세션/상태/카테고리) → 보낼 곳 or null.
// 역할 정보구조 재설계(설계 §3·§10)에 맞춰 카테고리를 세분화했다:
// - landing: '/labeling' 진입점 — 두 역할이 각자의 홈을 렌더하므로 어느 역할도 튕기지 않는다.
// - shared : 영상 보관함·canary 동일 링크 — 승인 라벨러/Owner 모두 접근하는 읽기 경로.
// - labeler: 내 기록·이중 블라인드 작업 — 라벨러 전용, Owner 는 owner 홈으로 정렬.
// - owner  : 운영 현황·불일치 검수·팀 관리·연구/직접 라벨링 큐 — Owner 전용.
//   labeler 가 URL 직접 입력하면 라벨러 홈(/labeling)으로 튕긴다.

import type { LabelingAccessInfo } from './labelingApi';

export type RouteCategory =
  | 'public'
  | 'apply'
  | 'pending'
  | 'owner'
  | 'labeler'
  | 'shared'
  | 'tutorial'
  | 'landing';

export function categorize(pathname: string): RouteCategory {
  if (
    pathname.startsWith('/labeling/login') ||
    pathname.startsWith('/labeling/signup')
  ) {
    return 'public';
  }
  if (pathname === '/labeling/apply') return 'apply';
  if (pathname === '/labeling/pending') return 'pending';
  if (pathname.startsWith('/labeling/tutorial')) return 'tutorial';

  // canary 동일 링크는 일반 /labeling/blind/** 보다 먼저 분류한다(설계 §8, 역할별 렌더 공용 경로).
  if (pathname.startsWith('/labeling/blind/canary')) return 'shared';
  // 이중 블라인드 owner 화면(불일치 검수·그룹 배정)은 owner 전용(설계 §7).
  if (
    pathname.startsWith('/labeling/blind/conflicts') ||
    pathname.startsWith('/labeling/blind/groups')
  ) {
    return 'owner';
  }
  // 그 외 /labeling/blind/**(활동일 상세)는 라벨러 작업 경로.
  if (pathname.startsWith('/labeling/blind/')) return 'labeler';

  // 공용 읽기 전용 영상 보관함 — 모든 승인 사용자(설계 §5.3).
  if (pathname.startsWith('/labeling/library')) return 'shared';

  // 라벨러 개인 기록.
  if (pathname.startsWith('/labeling/me')) return 'labeler';

  // Owner 전용 — 운영 현황·연구 도구·직접 라벨링 큐·팀 관리·격리함(설계 §7).
  if (
    pathname.startsWith('/labeling/owner') ||
    pathname.startsWith('/labeling/team') ||
    pathname.startsWith('/labeling/quarantine') ||
    pathname.startsWith('/labeling/router-review') ||
    pathname.startsWith('/labeling/motion') ||
    pathname.startsWith('/labeling/legacy')
  ) {
    return 'owner';
  }

  // '/labeling' 정확히 = landing. 두 역할이 각자의 홈을 렌더한다.
  return 'landing';
}

// 현재 경로가 접근 상태에 맞으면 null, 아니면 보내야 할 목적지.
// 역할 홈: owner=/labeling/owner, labeler=/labeling. 튜토리얼 미완료 labeler 는 업무 경로 대신
// 튜토리얼로(설계 §8). pending/rejected 는 대기, unregistered 는 신청 화면으로 정렬(§3.3).
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
      // Owner 접근 가능: landing·owner·shared·tutorial. 라벨러 전용/신청/대기 경로는 owner 홈으로.
      return cat === 'landing' || cat === 'owner' || cat === 'shared' || cat === 'tutorial'
        ? null
        : '/labeling/owner';
    case 'labeler':
      if (cat === 'tutorial') return null;
      // 라벨러 업무 경로: landing·labeler·shared. 미완료면 튜토리얼로 먼저 보낸다.
      if (cat === 'landing' || cat === 'labeler' || cat === 'shared') {
        return tutorialRequired ? '/labeling/tutorial' : null;
      }
      // owner 전용·신청·대기 경로 → 라벨러 홈.
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
