'use client';

// 역할별 반응형 셸 — desktop 사이드 메뉴 / mobile 하단 3탭(설계 §3·§9).
//
// 하나의 공통 메뉴를 숨기고 보이는 방식이 아니라(설계 §2 역할 우선), 역할마다 정확히 세 개의
// 업무 메뉴를 준다. 집중형 작업대 지향 — admin 대시보드가 아니다. 선택 메뉴는 검은 채움 대신
// emerald 아웃라인(border-emerald-500 bg-emerald-50 text-emerald-950).
//
// 반응형 계약(설계 §9): 320px 부터 하단 고정 3탭, lg 에서만 220px 사이드 메뉴 + 최대 1200px 본문.
// 메뉴명·숫자·버튼은 whitespace-nowrap, grid/flex 자식은 min-w-0, 루트는 overflow-x-clip 으로
// 가로 스크롤/잘림을 막는다. 긴 이메일·카메라 이름만 truncate + title.

import Link from 'next/link';

import {
  roleHome,
  roleNavItems,
  type LabelingRole,
  type RoleNavItem,
} from '@/lib/labelingRoleNavigation';
import AccountMenu from './_account-menu';

// 각 메뉴의 작은 아이콘(aria-hidden). 짧은 한글 라벨과 함께 하단 탭 가독성을 높인다.
const NAV_ICON: Record<string, string> = {
  '/labeling': '📋',
  '/labeling/me': '🗂️',
  '/labeling/library': '🎞️',
  '/labeling/owner': '📊',
  '/labeling/blind/conflicts': '⚖️',
  '/labeling/team': '👥',
  '/labeling/dashboard': '📈',
  '/labeling/boundary': '🔗',
  '/labeling/motion/cleanup': '🧹',
};

const ROLE_BADGE: Record<LabelingRole, string> = {
  owner: 'Owner',
  labeler: '라벨러',
  unapproved: '대기',
};

function isActive(item: RoleNavItem, pathname: string): boolean {
  if (pathname === item.href) return true;
  return item.activePrefixes.some((p) => pathname.startsWith(p));
}

function sideClass(active: boolean): string {
  return active
    ? 'flex items-center gap-2 rounded-md border border-emerald-500 bg-emerald-50 px-3 py-2 text-sm font-semibold text-emerald-950 whitespace-nowrap'
    : 'flex items-center gap-2 rounded-md border border-transparent px-3 py-2 text-sm text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900 whitespace-nowrap';
}

function tabClass(active: boolean): string {
  return active
    ? 'flex min-w-0 flex-col items-center gap-0.5 rounded-md border border-emerald-500 bg-emerald-50 py-1 text-xs font-semibold text-emerald-950 whitespace-nowrap'
    : 'flex min-w-0 flex-col items-center gap-0.5 rounded-md border border-transparent py-1 text-xs text-zinc-600 whitespace-nowrap';
}

export default function RoleShell({
  role,
  pathname,
  boundaryEnabled,
  email,
  onChangePassword,
  onSignOut,
  children,
}: {
  role: LabelingRole;
  pathname: string;
  boundaryEnabled: boolean;
  email: string;
  onChangePassword: () => void;
  onSignOut: () => void;
  children: React.ReactNode;
}) {
  const items = roleNavItems(role, boundaryEnabled);
  const hasNav = items.length > 0;

  return (
    <div className="min-h-screen overflow-x-clip bg-zinc-50">
      <header className="sticky top-0 z-40 border-b border-zinc-200 bg-white/95 backdrop-blur">
        <div className="mx-auto flex min-w-0 max-w-[1484px] items-center gap-3 px-4 py-3">
          <Link href={roleHome(role)} prefetch={false} className="flex min-w-0 items-center gap-2">
            <span className="grid h-7 w-7 shrink-0 place-items-center rounded-md bg-emerald-600 text-xs font-semibold text-white">
              R
            </span>
            <span className="whitespace-nowrap text-sm font-semibold tracking-tight text-zinc-900">
              petcam 라벨링
            </span>
            <span className="whitespace-nowrap rounded-md bg-emerald-50 px-1.5 py-0.5 text-[11px] font-semibold text-emerald-700 ring-1 ring-inset ring-emerald-200">
              {ROLE_BADGE[role]}
            </span>
          </Link>
          <div className="ml-auto min-w-0">
            <AccountMenu email={email} onChangePassword={onChangePassword} onSignOut={onSignOut} />
          </div>
        </div>
      </header>

      {hasNav ? (
        <div className="mx-auto min-w-0 max-w-[1484px] px-4 lg:grid lg:grid-cols-[220px_minmax(0,1200px)] lg:gap-8">
          <aside className="hidden lg:block lg:py-6">
            <nav className="flex flex-col gap-1">
              {items.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  prefetch={false}
                  className={sideClass(isActive(item, pathname))}
                >
                  <span aria-hidden>{NAV_ICON[item.href] ?? '•'}</span>
                  <span className="min-w-0 truncate">{item.label}</span>
                </Link>
              ))}
            </nav>
          </aside>
          <div className="min-w-0 pb-24 lg:pb-8">{children}</div>
        </div>
      ) : (
        <div className="mx-auto min-w-0 max-w-2xl px-4 pb-12">{children}</div>
      )}

      {hasNav && (
        <nav
          className="fixed inset-x-0 bottom-0 z-40 grid gap-1 border-t border-zinc-200 bg-white p-2 lg:hidden"
          style={{ gridTemplateColumns: `repeat(${items.length}, minmax(0, 1fr))` }}
        >
          {items.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              prefetch={false}
              className={tabClass(isActive(item, pathname))}
            >
              <span aria-hidden className="text-base leading-none">
                {NAV_ICON[item.href] ?? '•'}
              </span>
              <span className="min-w-0 truncate">{item.mobileLabel ?? item.label}</span>
            </Link>
          ))}
        </nav>
      )}
    </div>
  );
}
