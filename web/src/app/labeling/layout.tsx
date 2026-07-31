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

import { useCallback, useEffect, useRef, useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import type { Session } from '@supabase/supabase-js';

import { getSupabaseBrowser } from '@/lib/supabaseBrowser';
import {
  UnauthorizedError,
  getLabelingAccess,
  type LabelingAccessInfo,
} from '@/lib/labelingApi';
import { decideAuthTransition } from '@/lib/labelingAuthEvents';
import { categorize, redirectTarget } from '@/lib/labelingRouteAccess';
import { resolveLabelingRole } from '@/lib/labelingRoleNavigation';
import Button from '@/components/ui/Button';
import { Card, CardTitle } from '@/components/ui/Card';
import ChangePasswordModal from './_change-password-modal';
import RoleShell from './_role-shell';
import { LabelingAccessProvider } from './_owner-context';

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
  // onAuthStateChange 콜백 안에서 직전 user id 를 알기 위한 ref(§9.2 결정 입력).
  const sessionRef = useRef<Session | null>(null);
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
      sessionRef.current = data.session;
      setSession(data.session);
      setChecked(true);
    });

    const {
      data: { subscription },
    } = sb.auth.onAuthStateChange((event, s) => {
      if (!mounted) return;
      // 이벤트 종류로 처리를 나눈다(§9.2) — 토큰 자동 갱신엔 child·access 를 유지해 입력을 지킨다.
      const decision = decideAuthTransition(
        event,
        sessionRef.current?.user.id ?? null,
        s?.user.id ?? null,
      );
      sessionRef.current = s;
      setSession(s);
      if (decision === 'keep') return;
      // recheck → 접근 재확인(로딩), discard → 접근 폐기 후 로그인으로.
      setAccess(null);
      setAccessError(null);
      setAccessChecked(decision === 'discard');
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

  // 공개 페이지(login/signup)는 자체 전체화면 카드 — 셸 크롬 없이 즉시 렌더한다(세션 대기 X).
  if (cat === 'public') return <>{children}</>;

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

  // 역할 판정(설계 §3.2 Owner→라벨러→미승인). 내비게이션은 RoleShell 에 위임하고, layout 은
  // 인증·접근 게이트와 비밀번호 모달만 유지한다. 튜토리얼 미완료 gating 은 redirectTarget 이 담당.
  const role = resolveLabelingRole(status);

  return (
    <LabelingAccessProvider value={{ access, refresh, userId: session?.user.id ?? null }}>
      <RoleShell
        role={role}
        pathname={pathname}
        boundaryEnabled={Boolean(access?.boundary_enabled)}
        email={session?.user.email ?? ''}
        onChangePassword={() => setPwModalOpen(true)}
        onSignOut={signOut}
      >
        {children}
      </RoleShell>

      <ChangePasswordModal
        open={pwModalOpen}
        onClose={() => setPwModalOpen(false)}
      />
    </LabelingAccessProvider>
  );
}
