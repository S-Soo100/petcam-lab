'use client';

// 라벨링 영역 레이아웃 — 인증 게이트.
//
// 왜 클라이언트 컴포넌트?
// - Supabase Auth 세션은 localStorage 보관 (persistSession). 서버에서 못 읽음.
// - SSR 인증을 하려면 @supabase/ssr 또는 cookie 어댑터가 필요한데, MVP 는 단순화.
// - layout 이 client 면 자식 페이지들도 자연스럽게 client 로 정렬.
//
// 동작:
// 1. 마운트 시 세션 확인 → 없으면 /labeling/login 리다이렉트
// 2. onAuthStateChange 구독 → 다른 탭에서 로그아웃 시 즉시 로그인 페이지로
// 3. /labeling/login 자체는 게이트 우회 (else 무한 리다이렉트)

import { useEffect, useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import Link from 'next/link';
import type { Session } from '@supabase/supabase-js';

import { getSupabaseBrowser } from '@/lib/supabaseBrowser';
import Button from '@/components/ui/Button';
import ChangePasswordModal from './_change-password-modal';

export default function LabelingLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const pathname = usePathname() || '';
  const isLoginPage = pathname.startsWith('/labeling/login');

  const [session, setSession] = useState<Session | null>(null);
  const [checked, setChecked] = useState(false);
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
    });

    return () => {
      mounted = false;
      subscription.unsubscribe();
    };
  }, []);

  useEffect(() => {
    if (!checked) return;
    if (!session && !isLoginPage) {
      router.replace('/labeling/login');
    }
  }, [checked, session, isLoginPage, router]);

  async function signOut() {
    const sb = getSupabaseBrowser();
    await sb.auth.signOut();
    router.replace('/labeling/login');
  }

  // 첫 마운트 시 깜빡임 방지 — 세션 확인 끝날 때까지 빈 화면.
  if (!checked) {
    return <div className="min-h-screen bg-zinc-50" />;
  }

  return (
    <div className="min-h-screen bg-zinc-50">
      <header className="sticky top-0 z-30 border-b border-zinc-200 bg-white/80 backdrop-blur">
        <div className="mx-auto flex max-w-4xl items-center gap-4 px-6 py-3">
          <Link href="/labeling" className="flex items-center gap-2">
            <span className="grid h-7 w-7 place-items-center rounded-md bg-emerald-600 text-xs font-semibold text-white">
              GT
            </span>
            <span className="text-sm font-semibold tracking-tight text-zinc-900">
              petcam 라벨링
            </span>
          </Link>
          <nav className="flex items-center gap-1 text-sm">
            {session && (
              <>
                <Link
                  href="/labeling"
                  prefetch={false}
                  className={`rounded-md px-3 py-1.5 transition-colors ${
                    pathname === '/labeling'
                      ? 'bg-zinc-900 text-white'
                      : 'text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900'
                  }`}
                >
                  큐
                </Link>
                <Link
                  href="/labeling/me"
                  prefetch={false}
                  className={`rounded-md px-3 py-1.5 transition-colors ${
                    pathname === '/labeling/me'
                      ? 'bg-zinc-900 text-white'
                      : 'text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900'
                  }`}
                >
                  내 라벨
                </Link>
              </>
            )}
          </nav>
          <div className="ml-auto flex items-center gap-3 text-xs text-zinc-500">
            {session && (
              <>
                <span className="truncate max-w-[180px]" title={session.user.email || ''}>
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

      {children}

      <ChangePasswordModal
        open={pwModalOpen}
        onClose={() => setPwModalOpen(false)}
      />
    </div>
  );
}
