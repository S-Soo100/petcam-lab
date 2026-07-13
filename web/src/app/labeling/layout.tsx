'use client';

// 라벨링 영역 레이아웃 — 인증 + 라벨링 접근 게이트.
//
// 왜 클라이언트 컴포넌트?
// - Supabase Auth 세션은 localStorage 보관(persistSession). 서버에서 못 읽음.
// - layout 이 client 면 자식 페이지도 자연스럽게 client 로 정렬.
//
// 동작:
// 1. 세션 확인 → 없으면 공개 경로만 통과, 나머지는 /labeling/login.
// 2. 세션 있으면 GET /api/labeling-access 로 상태 확정 전까지 중립 화면(§4.7) —
//    pending 사용자가 큐/메뉴를 흘깃 보는 것을 막는다.
// 3. 상태별로 허용 경로가 아니면 목적지로 리다이렉트. 내비게이션도 상태로 렌더.

import { useCallback, useEffect, useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import Link from 'next/link';
import type { Session } from '@supabase/supabase-js';

import { getSupabaseBrowser } from '@/lib/supabaseBrowser';
import {
  UnauthorizedError,
  getLabelingAccess,
  type LabelingAccessInfo,
} from '@/lib/labelingApi';
import Button from '@/components/ui/Button';
import { Card, CardTitle } from '@/components/ui/Card';
import ChangePasswordModal from './_change-password-modal';
import { LabelingAccessProvider } from './_owner-context';

type RouteCategory = 'public' | 'apply' | 'pending' | 'owner' | 'tutorial' | 'work';

function categorize(pathname: string): RouteCategory {
  if (
    pathname.startsWith('/labeling/login') ||
    pathname.startsWith('/labeling/signup')
  ) {
    return 'public';
  }
  if (pathname === '/labeling/apply') return 'apply';
  if (pathname === '/labeling/pending') return 'pending';
  if (pathname.startsWith('/labeling/team')) return 'owner';
  if (pathname.startsWith('/labeling/tutorial')) return 'tutorial';
  return 'work'; // 큐, 단건 상세, 내 라벨, 라우터 리뷰
}

// 현재 경로가 접근 상태에 맞으면 null, 아니면 보내야 할 목적지.
// owner/labeler 는 apply·pending 에서 자동 이탈, pending/rejected 는 대기 화면,
// unregistered 는 신청 화면으로 정렬한다(§5).
function redirectTarget(
  hasSession: boolean,
  status: LabelingAccessInfo['status'] | null,
  cat: RouteCategory,
  tutorialRequired: boolean,
): string | null {
  // 공개 페이지(login/signup)는 로그인 여부와 무관하게 항상 렌더 — 페이지가 스스로 라우팅한다.
  // 이렇게 해야 가입 직후(session 생성 → 아직 신청 row 없음) 레이아웃이 signup 을 apply 로
  // 튕겨 흐름을 끊는 레이스를 막는다.
  if (cat === 'public') return null;
  if (!hasSession) return '/labeling/login';
  switch (status) {
    case 'owner':
      // owner 는 튜토리얼도 preview 가능. 면제이므로 work 로 튕기지 않는다.
      return cat === 'work' || cat === 'owner' || cat === 'tutorial' ? null : '/labeling';
    case 'labeler':
      // 튜토리얼 미완료(required) labeler 는 본 큐 대신 튜토리얼로(설계 §8).
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

function NeutralScreen() {
  return <div className="min-h-screen bg-zinc-50" />;
}

export default function LabelingLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const pathname = usePathname() || '';
  const cat = categorize(pathname);

  const [session, setSession] = useState<Session | null>(null);
  const [checked, setChecked] = useState(false);
  const [access, setAccess] = useState<LabelingAccessInfo | null>(null);
  const [accessChecked, setAccessChecked] = useState(false);
  const [accessError, setAccessError] = useState<string | null>(null);
  const [pwModalOpen, setPwModalOpen] = useState(false);

  useEffect(() => {
    const sb = getSupabaseBrowser();
    let mounted = true;

    sb.auth.getSession().then(({ data }) => {
      if (!mounted) return;
      setSession(data.session);
      setChecked(true);
    });

    const {
      data: { subscription },
    } = sb.auth.onAuthStateChange((_event, s) => {
      if (!mounted) return;
      setSession(s);
      // 세션이 바뀌면 접근 상태를 다시 확인한다.
      setAccess(null);
      setAccessChecked(false);
      setAccessError(null);
    });

    return () => {
      mounted = false;
      subscription.unsubscribe();
    };
  }, []);

  // pending 페이지의 "상태 새로고침" 등에서 재확인을 트리거.
  const refresh = useCallback(() => {
    setAccessChecked(false);
    setAccessError(null);
  }, []);

  useEffect(() => {
    if (!checked) return;
    if (!session) {
      setAccess(null);
      setAccessChecked(true);
      return;
    }
    if (accessChecked) return;
    let cancelled = false;
    getLabelingAccess()
      .then((info) => {
        if (cancelled) return;
        setAccess(info);
        setAccessChecked(true);
      })
      .catch((cause) => {
        if (cancelled) return;
        if (cause instanceof UnauthorizedError) {
          getSupabaseBrowser()
            .auth.signOut()
            .finally(() => router.replace('/labeling/login'));
          return;
        }
        setAccessError((cause as Error).message);
        setAccessChecked(true);
      });
    return () => {
      cancelled = true;
    };
  }, [checked, session, accessChecked, router]);

  const status = access?.status ?? null;
  const target = redirectTarget(
    Boolean(session),
    status,
    cat,
    Boolean(access?.tutorial?.required),
  );

  useEffect(() => {
    if (!checked) return;
    if (session && !accessChecked) return;
    if (accessError) return;
    if (target && target !== pathname) router.replace(target);
  }, [checked, session, accessChecked, accessError, target, pathname, router]);

  async function signOut() {
    await getSupabaseBrowser().auth.signOut();
    router.replace('/labeling/login');
  }

  if (!checked) return <NeutralScreen />;
  if (session && !accessChecked) return <NeutralScreen />;

  if (accessError) {
    return (
      <main className="mx-auto max-w-md px-6 py-16">
        <Card padding="lg">
          <CardTitle>접근 상태를 확인하지 못했어</CardTitle>
          <p className="mt-2 text-sm text-zinc-600">{accessError}</p>
          <div className="mt-4 flex gap-2">
            <Button onClick={refresh}>다시 시도</Button>
            <Button variant="secondary" onClick={signOut}>
              로그아웃
            </Button>
          </div>
        </Card>
      </main>
    );
  }

  if (target && target !== pathname) return <NeutralScreen />;

  const showWorkNav = status === 'owner' || status === 'labeler';
  const showTeamNav = status === 'owner';
  const navLink = (href: string, label: string, activeWhen: boolean) => (
    <Link
      href={href}
      prefetch={false}
      className={`rounded-md px-3 py-1.5 transition-colors ${
        activeWhen
          ? 'bg-zinc-900 text-white'
          : 'text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900'
      }`}
    >
      {label}
    </Link>
  );

  return (
    <div className="min-h-screen bg-zinc-50">
      <header className="sticky top-0 z-30 border-b border-zinc-200 bg-white/80 backdrop-blur">
        <div className="mx-auto flex max-w-4xl items-center gap-4 px-6 py-3">
          <Link href="/labeling" className="flex items-center gap-2">
            <span className="grid h-7 w-7 place-items-center rounded-md bg-emerald-600 text-xs font-semibold text-white">
              R
            </span>
            <span className="flex items-center gap-2">
              <span className="text-sm font-semibold tracking-tight text-zinc-900">
                petcam 라벨링
              </span>
              <span className="rounded-md bg-emerald-50 px-1.5 py-0.5 text-[11px] font-semibold text-emerald-700 ring-1 ring-inset ring-emerald-200">
                RBA 1.0
              </span>
            </span>
          </Link>
          <nav className="flex items-center gap-1 text-sm">
            {showWorkNav && (
              <>
                {navLink('/labeling', '큐', pathname === '/labeling')}
                {navLink('/labeling/me', '내 라벨', pathname === '/labeling/me')}
                {navLink(
                  '/labeling/router-review',
                  '라우터 리뷰',
                  pathname.startsWith('/labeling/router-review'),
                )}
                <Link
                  href="/labeling/tutorial"
                  prefetch={false}
                  className={`rounded-md px-3 py-1.5 transition-colors ${
                    pathname.startsWith('/labeling/tutorial')
                      ? 'bg-zinc-900 text-white'
                      : access?.tutorial?.required
                        ? 'bg-amber-100 font-medium text-amber-800 hover:bg-amber-200'
                        : 'text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900'
                  }`}
                >
                  {access?.tutorial?.required
                    ? `튜토리얼 · 필수 ${access.tutorial.completed_lessons}/${access.tutorial.total_lessons}`
                    : '튜토리얼'}
                </Link>
              </>
            )}
            {showTeamNav &&
              navLink(
                '/labeling/team',
                '팀원 관리',
                pathname.startsWith('/labeling/team'),
              )}
          </nav>
          <div className="ml-auto flex items-center gap-3 text-xs text-zinc-500">
            {session && (
              <>
                <span
                  className="max-w-[180px] truncate"
                  title={session.user.email || ''}
                >
                  {session.user.email}
                </span>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => setPwModalOpen(true)}
                >
                  비번 변경
                </Button>
                <Button variant="secondary" size="sm" onClick={signOut}>
                  로그아웃
                </Button>
              </>
            )}
          </div>
        </div>
      </header>

      <LabelingAccessProvider value={{ access, refresh }}>
        {children}
      </LabelingAccessProvider>

      <ChangePasswordModal
        open={pwModalOpen}
        onClose={() => setPwModalOpen(false)}
      />
    </div>
  );
}
