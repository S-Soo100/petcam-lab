'use client';

// 라벨러 로그인 — Supabase Auth email/password.
//
// 왜 email/password (magic link 아니고)?
// - MVP 라벨러 ≤ 3 명, 모두 팀원 → 비번 한 번 만들고 끝.
// - magic link 는 메일 받기 → 클릭 → 다시 web 으로 왕복. 초기 셋업 시 번거로움.
// - 둘 다 Supabase Auth 표준이라 나중에 추가 가능.
//
// labelers 테이블 등록은 별도 — Supabase Studio / SQL 에서 수동.
// 즉, 가입 자체는 service_role 이 SQL 로 직접 (auth.users INSERT) — 일반인 회원가입 막음.
// 이 페이지는 로그인만, 회원가입 폼 없음.

import { FormEvent, useState } from 'react';
import { useRouter } from 'next/navigation';

import { getSupabaseBrowser } from '@/lib/supabaseBrowser';
import Button from '@/components/ui/Button';
import { Card, CardTitle } from '@/components/ui/Card';

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);

    const sb = getSupabaseBrowser();
    const { error } = await sb.auth.signInWithPassword({ email, password });

    setBusy(false);
    if (error) {
      setErr(error.message);
      return;
    }
    router.replace('/labeling');
  }

  return (
    <main className="mx-auto max-w-md px-6 py-16">
      <Card padding="lg">
        <CardTitle>petcam 라벨러 로그인</CardTitle>
        <p className="mt-1 text-xs text-zinc-500">
          팀 라벨러만 접근 가능. 계정 추가는 백엔드 관리자에게 요청.
        </p>

        <form className="mt-5 space-y-3" onSubmit={handleSubmit}>
          <label className="block">
            <span className="text-xs font-medium text-zinc-700">이메일</span>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoComplete="email"
              autoFocus
              className="mt-1 block w-full rounded-md border border-zinc-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
            />
          </label>
          <label className="block">
            <span className="text-xs font-medium text-zinc-700">비밀번호</span>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete="current-password"
              className="mt-1 block w-full rounded-md border border-zinc-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
            />
          </label>

          {err && (
            <div className="rounded-md bg-red-50 px-3 py-2 text-xs text-red-700 ring-1 ring-inset ring-red-200">
              {err}
            </div>
          )}

          <Button
            type="submit"
            disabled={busy || !email || !password}
            className="w-full"
            size="lg"
          >
            {busy ? '로그인 중…' : '로그인'}
          </Button>
        </form>
      </Card>
    </main>
  );
}
