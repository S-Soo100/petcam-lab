// 라벨링 영역 경로 접근 판정 — layout.tsx 에서 추출한 순수 로직(테스트 대상).
//
// categorize: pathname → 접근 카테고리. redirectTarget: (세션/상태/카테고리) → 보낼 곳 or null.
// 역할 정보구조 재설계(설계 §3·§10)에 맞춰 카테고리를 세분화했다:
// - landing: '/labeling' 진입점 — 두 역할이 각자의 홈을 렌더하므로 어느 역할도 튕기지 않는다.
// - shared : 영상 보관함·v4 목록/상세(내 카메라·전체·확정) — 승인 라벨러/Owner 모두 접근.
// - labeler: 게코 박스 — 라벨러 전용, Owner 는 owner 홈으로 정렬.
// - owner  : 운영 현황·팀 관리·연구/직접 라벨링 큐 — Owner 전용.
//   labeler 가 URL 직접 입력하면 라벨러 홈(/labeling/mine)으로 튕긴다.
// - invalid: 퇴역한 이중 blind·내 기록·튜토리얼 경로 등 — 역할 홈으로 돌려보낸다.

import type { LabelingAccessInfo } from './labelingApi';

// motion v3 직접 상세(`/labeling/<clipId>`)의 clipId 는 canonical UUID 다. 단일 세그먼트 UUID 만
// owner 로 접기 위한 패턴(다른 `/labeling/<word>` 는 landing 유지).
const CLIP_UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// 퇴역 경로(이중 blind 트랙·내 기록·대화형 튜토리얼). 라우트 파일은 삭제됐고 URL 만 역할 홈으로 접는다.
// 튜토리얼은 2026-09-07 owner 결정으로 퇴역(docs/decision-gate.md 4차).
const RETIRED_PATHS = ['/labeling/blind', '/labeling/me', '/labeling/tutorial'] as const;

// 세그먼트 경계 매칭 — `/labeling/me` 가 `/labeling/members` 를, `/labeling/blind` 가 `/labeling/blindfold` 를
// 삼키지 않게 정확히 같거나 `base/` 로 이어질 때만 참.
export function matchesSegment(pathname: string, base: string): boolean {
  return pathname === base || pathname.startsWith(`${base}/`);
}

export type RouteCategory =
  | 'public'
  | 'apply'
  | 'pending'
  | 'owner'
  | 'labeler'
  | 'shared'
  | 'invalid'
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

  // boundary 해결은 owner 전용. 일반 boundary 작업은 아래 shared로 두고 assignment API가 제한한다.
  if (pathname.startsWith('/labeling/boundary/conflicts')) return 'owner';

  // v4 목록·상세 — 승인 역할 공용. 배정은 필터일 뿐이라 권한 경계가 아니다(v4 스펙 §4.1).
  if (pathname === '/labeling/mine' || pathname === '/labeling/all') return 'shared';
  if (pathname.startsWith('/labeling/v4/')) {
    return CLIP_UUID.test(pathname.slice('/labeling/v4/'.length)) ? 'shared' : 'invalid';
  }
  // 퇴역 경로(이중 blind 작업·내 기록·튜토리얼, 2026-09-08)는 역할 홈으로.
  if (RETIRED_PATHS.some((base) => matchesSegment(pathname, base))) return 'invalid';

  // GME Owner adjudication은 reviewer 공용 경로보다 먼저 잠그고, reviewer 공용은
  // exact root/canonical item UUID만 연다. 나머지 suffix를 landing으로 접으면 승인 역할이
  // 모두 통과하므로 invalid로 분리해 역할 홈으로 돌려보낸다.
  if (
    pathname === '/labeling/gme-audit/owner' ||
    pathname.startsWith('/labeling/gme-audit/owner/')
  ) return 'owner';
  if (pathname === '/labeling/gme-audit') return 'shared';
  if (pathname.startsWith('/labeling/gme-audit/')) {
    const itemId = pathname.slice('/labeling/gme-audit/'.length);
    return CLIP_UUID.test(itemId) ? 'shared' : 'invalid';
  }

  // 공용 읽기 전용 영상 보관함 — 모든 승인 사용자(설계 §5.3).
  if (
    pathname.startsWith('/labeling/library') ||
    pathname.startsWith('/labeling/dashboard') ||
    pathname.startsWith('/labeling/boundary')
  ) return 'shared';

  // 라벨러 전용 — 게코 박스.
  if (pathname.startsWith('/labeling/yolo')) return 'labeler';

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

  // '/labeling/<uuid>' = motion v3 owner 직접 라벨링 상세(GT 잠금·VLM 검수·미디어 API 진입점).
  // 미분류 fallthrough 로 landing 이 되면 승인 라벨러가 URL 로 열어 기존 정답을 볼 수 있으므로
  // owner 전용으로 고정한다(설계 §10·review-fix P0-2). 서버 API 는 별도로 owner-only 로 잠근다.
  const seg = pathname.startsWith('/labeling/') ? pathname.slice('/labeling/'.length) : '';
  if (seg && CLIP_UUID.test(seg)) return 'owner';

  // '/labeling' 정확히 = landing. 두 역할이 각자의 홈을 렌더한다.
  return 'landing';
}

// 현재 경로가 접근 상태에 맞으면 null, 아니면 보내야 할 목적지.
// 역할 홈: owner=/labeling/owner, labeler=/labeling/mine. pending/rejected 는 대기, unregistered 는
// 신청 화면으로 정렬(§3.3). (튜토리얼 미완료 분기는 트랙 퇴역으로 2026-09-07 제거.)
export function redirectTarget(
  hasSession: boolean,
  status: LabelingAccessInfo['status'] | null,
  cat: RouteCategory,
): string | null {
  // 공개 페이지(login/signup)는 로그인 여부와 무관하게 항상 렌더 — 페이지가 스스로 라우팅한다.
  if (cat === 'public') return null;
  if (!hasSession) return '/labeling/login';
  switch (status) {
    case 'owner':
      // Owner 접근 가능: landing·owner·shared. 라벨러 전용/신청/대기 경로는 owner 홈으로.
      return cat === 'landing' || cat === 'owner' || cat === 'shared'
        ? null
        : '/labeling/owner';
    case 'labeler':
      // 라벨러 업무 경로: landing·labeler·shared.
      if (cat === 'landing' || cat === 'labeler' || cat === 'shared') return null;
      // owner 전용·신청·대기·퇴역 경로 → 라벨러 홈(내 카메라).
      return '/labeling/mine';
    case 'pending':
    case 'rejected':
      return cat === 'pending' ? null : '/labeling/pending';
    case 'unregistered':
      return cat === 'apply' ? null : '/labeling/apply';
    default:
      return null; // 상태 미확정 — 상위 로딩 처리
  }
}
