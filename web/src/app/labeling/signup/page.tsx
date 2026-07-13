'use client';

// 공개 회원가입 — Supabase Auth 가입 + 라벨러 참여 신청을 한 번에(§4.2).
//
// 흐름:
// 1. auth.signUp({ email, password, options: { data: { display_name }}})
// 2. 세션이 생기면 POST /api/labeler-applications
// 3. 성공 → /labeling/pending
//
// email confirmation 은 비활성 전제. 설정이 바뀌어 세션이 안 오면 성공으로 가장하지 않고
// 명확히 안내한다(§4.2). Auth 는 됐는데 신청만 실패하면 로그인 유지 후 /labeling/apply 재시도(§3.1).

import { FormEvent, useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';

import { getSupabaseBrowser } from '@/lib/supabaseBrowser';
import { applyForLabeling } from '@/lib/labelingApi';
import Button from '@/components/ui/Button';
import { Card, CardTitle } from '@/components/ui/Card';

const MIN_PASSWORD = 6; // Supabase 기본 최소 길이. 실제 정책은 서버가 최종 검증.

export default function SignupPage() {
  const router = useRouter();
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setErr(null);

    const displayName = name.trim();
    if (displayName.length < 1 || displayName.length > 80) {
      setErr('이름은 공백을 제외하고 1~80자여야 해.');
      return;
    }
    if (password.length < MIN_PASSWORD) {
      setErr(`비밀번호는 ${MIN_PASSWORD}자 이상이어야 해.`);
      return;
    }
    if (password !== confirm) {
      setErr('비밀번호 확인이 일치하지 않아.');
      return;
    }

    setBusy(true);
    const sb = getSupabaseBrowser();
    const { data, error } = await sb.auth.signUp({
      email,
      password,
      options: { data: { display_name: displayName } },
    });

    if (error) {
      setBusy(false);
      if (/already|exists|registered/i.test(error.message)) {
        setErr('이미 계정이 있다면 로그인해줘.');
      } else {
        setErr(error.message);
      }
      return;
    }

    // 이미 존재하는 이메일이면 Supabase 가 열거 방지를 위해 identities 를 비운 user 를 준다.
    if (data.user && (data.user.identities?.length ?? 0) === 0) {
      setBusy(false);
      setErr('이미 계정이 있다면 로그인해줘.');
      return;
    }

    if (!data.session) {
      // email confirmation 이 켜졌거나 세션을 못 만든 경우 — 성공으로 가장하지 않는다.
      setBusy(false);
      setErr('로그인 세션을 만들지 못했어. 관리자에게 문의해.');
      return;
    }

    // 세션 확보 → 라벨러 신청. 신청만 실패하면 로그인 유지 후 apply 에서 재시도.
    try {
      await applyForLabeling(displayName);
      router.replace('/labeling/pending');
    } catch {
      router.replace('/labeling/apply');
    }
  }

  return (
    <main className="mx-auto max-w-md px-6 py-16">
      <Card padding="lg">
        <div className="flex items-center justify-between gap-3">
          <CardTitle>petcam 라벨러 회원가입</CardTitle>
          <span className="rounded-md bg-emerald-50 px-1.5 py-0.5 text-[11px] font-semibold text-emerald-700 ring-1 ring-inset ring-emerald-200">
            RBA 1.0
          </span>
        </div>
        <p className="mt-1 text-xs text-zinc-500">
          가입 후 관리자 승인을 받아야 영상 데이터에 접근할 수 있어.
        </p>

        <form className="mt-5 space-y-3" onSubmit={handleSubmit}>
          <label className="block">
            <span className="text-xs font-medium text-zinc-700">이름</span>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              maxLength={80}
              autoFocus
              className="mt-1 block w-full rounded-md border border-zinc-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
            />
          </label>
          <label className="block">
            <span className="text-xs font-medium text-zinc-700">이메일</span>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoComplete="email"
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
              minLength={MIN_PASSWORD}
              autoComplete="new-password"
              className="mt-1 block w-full rounded-md border border-zinc-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
            />
          </label>
          <label className="block">
            <span className="text-xs font-medium text-zinc-700">
              비밀번호 확인
            </span>
            <input
              type="password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              required
              minLength={MIN_PASSWORD}
              autoComplete="new-password"
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
            disabled={busy || !name || !email || !password || !confirm}
            className="w-full"
            size="lg"
          >
            {busy ? '가입 중…' : '회원가입'}
          </Button>
        </form>

        <p className="mt-4 text-center text-xs text-zinc-500">
          이미 계정이 있어?{' '}
          <Link
            href="/labeling/login"
            className="font-medium text-emerald-600 hover:text-emerald-700"
          >
            로그인
          </Link>
        </p>
      </Card>
    </main>
  );
}
