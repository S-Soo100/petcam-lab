// 역할별 홈·메뉴·경로 접근 순수 계약 (설계 §3 역할 정의).
//
// 화면에서 메뉴를 숨기는 것은 보안 경계가 아니다(설계 §10) — 여기 값은 UI 계약이고,
// 실제 접근 차단은 서버 API 가 다시 판정한다. 이 파일은 순수 함수만 두어 테스트 가능하게 유지.
//
// 역할 판정 순서는 Owner → 승인 라벨러 → 미승인 사용자로 고정(설계 §3.2). Owner 가 동시에
// 라벨러 레코드를 가져도 기본 역할은 Owner 이고, 라벨링은 '직접 라벨링' 보조 버튼으로만 진입.

import type { LabelingAccessStatus } from './labelingApi';

export type LabelingRole = 'owner' | 'labeler' | 'unapproved';

export interface RoleNavItem {
  href: string;
  label: string;
  mobileLabel?: string;
  // 이 메뉴가 active 로 표시되는 경로 prefix 들(단일 메뉴가 여러 하위 경로를 대표).
  activePrefixes: readonly string[];
}

// v4(2026-09-08): 이중 blind '오늘 작업'·'내 기록'·'불일치 검수'는 퇴역. 라벨러 홈은 내 카메라(A),
// 두 역할 공용 전체(B) 목록에서 하이라이트 O/X 를 확정한다(v4 스펙 §2 In 3·4·8).
const NAV: Record<LabelingRole, readonly RoleNavItem[]> = {
  labeler: [
    { href: '/labeling/mine', label: '내 카메라', mobileLabel: '내 카메라', activePrefixes: ['/labeling/mine', '/labeling/v4/'] },
    { href: '/labeling/all', label: '전체', mobileLabel: '전체', activePrefixes: ['/labeling/all'] },
    { href: '/labeling/library', label: '영상 보기', mobileLabel: '영상', activePrefixes: ['/labeling/library'] },
    { href: '/labeling/dashboard', label: '데이터 현황', mobileLabel: '현황', activePrefixes: ['/labeling/dashboard'] },
    { href: '/labeling/yolo', label: '게코 박스', mobileLabel: '박스', activePrefixes: ['/labeling/yolo'] },
    { href: '/labeling/gme-audit', label: 'GME 점검', mobileLabel: 'GME', activePrefixes: ['/labeling/gme-audit'] },
  ],
  owner: [
    { href: '/labeling/owner', label: '운영 현황', mobileLabel: '운영', activePrefixes: ['/labeling/owner'] },
    { href: '/labeling/all', label: '전체', mobileLabel: '전체', activePrefixes: ['/labeling/all', '/labeling/mine', '/labeling/v4/'] },
    { href: '/labeling/team', label: '팀 관리', mobileLabel: '팀', activePrefixes: ['/labeling/team'] },
    { href: '/labeling/dashboard', label: '데이터 현황', mobileLabel: '현황', activePrefixes: ['/labeling/dashboard'] },
    { href: '/labeling/owner/yolo', label: '게코 연구', mobileLabel: '게코', activePrefixes: ['/labeling/owner/yolo'] },
    { href: '/labeling/gme-audit', label: 'GME 점검', mobileLabel: 'GME', activePrefixes: ['/labeling/gme-audit'] },
  ],
  unapproved: [],
};

// Owner → 승인 라벨러 → 미승인 순으로 판정(설계 §3.2 고정 순서). owner/labeler 외는 전부 미승인.
export function resolveLabelingRole(status: LabelingAccessStatus | null): LabelingRole {
  if (status === 'owner') return 'owner';
  if (status === 'labeler') return 'labeler';
  return 'unapproved';
}

export function roleHome(role: LabelingRole): string {
  if (role === 'owner') return '/labeling/owner';
  if (role === 'labeler') return '/labeling/mine';
  return '/labeling/pending';
}

const BOUNDARY_NAV: RoleNavItem = {
  href: '/labeling/boundary',
  label: '이어짐 확인',
  mobileLabel: '이어짐',
  activePrefixes: ['/labeling/boundary'],
};

export function roleNavItems(
  role: LabelingRole,
  boundaryEnabled = false,
): readonly RoleNavItem[] {
  if (role === 'unapproved' || !boundaryEnabled) return NAV[role];
  return [...NAV[role], BOUNDARY_NAV];
}
