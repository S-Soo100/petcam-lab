import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

// next/link 는 App Router context 를 요구하므로 테스트에선 순수 anchor 로 대체한다.
vi.mock('next/link', () => ({
  default: ({
    href,
    className,
    children,
  }: {
    href: string;
    className?: string;
    children: React.ReactNode;
    prefetch?: boolean;
  }) => (
    <a href={href} className={className}>
      {children}
    </a>
  ),
}));

import RoleShell from './_role-shell';

function render(role: 'owner' | 'labeler' | 'unapproved', pathname = '/labeling') {
  return renderToStaticMarkup(
    <RoleShell
      role={role}
      pathname={pathname}
      email="labeler@example.com"
      onChangePassword={() => {}}
      onSignOut={() => {}}
    >
      <div>본문</div>
    </RoleShell>,
  );
}

describe('RoleShell 메뉴 계약(설계 §3)', () => {
  it('라벨러 메뉴는 정확히 세 개, owner 메뉴는 없다', () => {
    const html = render('labeler');
    expect(html).toContain('오늘 작업');
    expect(html).toContain('내 기록');
    expect(html).toContain('영상 보기');
    expect(html).not.toContain('불일치 검수');
    expect(html).not.toContain('운영 현황');
  });

  it('owner 메뉴는 정확히 세 개, 연구 도구는 상시 노출 아님', () => {
    const html = render('owner', '/labeling/owner');
    expect(html).toContain('운영 현황');
    expect(html).toContain('불일치 검수');
    expect(html).toContain('팀 관리');
    expect(html).not.toContain('라우터 리뷰');
    expect(html).not.toContain('격리함');
    expect(html).not.toContain('오늘 작업');
  });

  it('미승인은 업무 nav 없이도 계정 메뉴(비밀번호 변경·로그아웃)는 셸로 접근한다', () => {
    const html = render('unapproved', '/labeling/pending');
    expect(html).not.toContain('<nav');
    expect(html).toContain('본문');
    // 계정 메뉴 트리거(이메일)는 미승인 역할에도 렌더된다 — 로그아웃/비번 변경 진입점.
    expect(html).toContain('labeler@example.com');
  });
});

describe('RoleShell 반응형 class 계약(설계 §9)', () => {
  it('하단 고정 3탭 + lg 사이드 그리드 + 잘림 방지 토큰', () => {
    const html = render('labeler');
    expect(html).toContain('min-w-0');
    expect(html).toContain('whitespace-nowrap');
    expect(html).toContain('overflow-x-clip');
    expect(html).toContain('fixed');
    expect(html).toContain('bottom-0');
    expect(html).toContain('grid-cols-3');
    expect(html).toContain('lg:grid');
    expect(html).toContain('lg:grid-cols-[220px_minmax(0,960px)]');
  });

  it('선택 메뉴는 검은 채움이 아니라 emerald 아웃라인', () => {
    const html = render('labeler', '/labeling');
    expect(html).not.toContain('bg-zinc-900 text-white');
    expect(html).toContain('border-emerald-500');
  });
});
