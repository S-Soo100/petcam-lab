'use client';

// 라벨러 로그인 — Supabase Auth email/password.
//
// 로그인 성공 후 '/' 로 보내지 않고 GET /api/labeling-access 결과로 직접 이동한다(§4.1):
// - owner, labeler → /labeling
// - pending, rejected → /labeling/pending
// - unregistered → /labeling/apply
// 하단에 회원가입 링크를 둔다 (공개 가입 허용).

import { FormEvent, useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';

import { getSupabaseBrowser } from '@/lib/supabaseBrowser';
import { getLabelingAccess } from '@/lib/labelingApi';
import Button from '@/components/ui/Button';
import { Card, CardTitle } from '@/components/ui/Card';

function destinationFor(status: string): string {
  if (status === 'owner' || status === 'labeler') return '/labeling';
  if (status === 'unregistered') return '/labeling/apply';
  return '/labeling/pending'; // pending, rejected
}

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
    if (error) {
      setBusy(false);
      setErr(error.message);
      return;
    }

    try {
      const access = await getLabelingAccess();
      router.replace(destinationFor(access.status));
    } catch {
      // access 조회 실패해도 레이아웃 게이트가 재판정하므로 큐로 보낸다.
      router.replace('/labeling');
    }
  }

  return (
    <main className="mx-auto max-w-md px-6 py-16">
      <Card padding="lg">
        <div className="flex items-center justify-between gap-3">
          <CardTitle>petcam 라벨러 로그인</CardTitle>
          <span className="rounded-md bg-emerald-50 px-1.5 py-0.5 text-[11px] font-semibold text-emerald-700 ring-1 ring-inset ring-emerald-200">
            RBA 1.0
          </span>
        </div>
        <p className="mt-1 text-xs text-zinc-500">
          팀 라벨러 전용. 가입 후 관리자 승인을 받아야 영상에 접근할 수 있어.
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

        <p className="mt-4 text-center text-xs text-zinc-500">
          계정이 없나?{' '}
          <Link
            href="/labeling/signup"
            className="font-medium text-emerald-600 hover:text-emerald-700"
          >
            회원가입
          </Link>
        </p>
      </Card>
    </main>
  );
}
