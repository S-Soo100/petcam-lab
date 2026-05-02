'use client';

// 비밀번호 변경 모달 — 로그인된 상태에서만 호출.
//
// Supabase auth.updateUser({password}) 는 현재 세션 토큰으로 인증.
// 분실(forgot) reset 은 별도 — 이 MVP 에선 미지원 (사용자 결정 옵션 A).

import { FormEvent, useEffect, useState } from 'react';

import { getSupabaseBrowser } from '@/lib/supabaseBrowser';
import Button from '@/components/ui/Button';

const MIN_LEN = 6; // Supabase 기본 정책

export default function ChangePasswordModal({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const [pw1, setPw1] = useState('');
  const [pw2, setPw2] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (!open) {
      setPw1('');
      setPw2('');
      setErr(null);
      setDone(false);
      setBusy(false);
    }
  }, [open]);

  // ESC 닫기
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setErr(null);

    if (pw1.length < MIN_LEN) {
      setErr(`비밀번호는 ${MIN_LEN}자 이상.`);
      return;
    }
    if (pw1 !== pw2) {
      setErr('두 입력이 다름.');
      return;
    }

    setBusy(true);
    const sb = getSupabaseBrowser();
    const { error } = await sb.auth.updateUser({ password: pw1 });
    setBusy(false);

    if (error) {
      setErr(error.message);
      return;
    }
    setDone(true);
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-sm rounded-lg bg-white p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between">
          <h2 className="text-base font-semibold text-zinc-900">비밀번호 변경</h2>
          <button
            type="button"
            onClick={onClose}
            className="text-zinc-400 hover:text-zinc-600"
            aria-label="닫기"
          >
            ×
          </button>
        </div>

        {done ? (
          <div className="mt-4 space-y-3">
            <div className="rounded-md bg-emerald-50 px-3 py-2 text-xs text-emerald-700 ring-1 ring-inset ring-emerald-200">
              변경 완료. 다음부터 새 비밀번호로 로그인해.
            </div>
            <Button onClick={onClose} className="w-full">
              닫기
            </Button>
          </div>
        ) : (
          <form className="mt-4 space-y-3" onSubmit={handleSubmit}>
            <label className="block">
              <span className="text-xs font-medium text-zinc-700">새 비밀번호</span>
              <input
                type="password"
                value={pw1}
                onChange={(e) => setPw1(e.target.value)}
                required
                minLength={MIN_LEN}
                autoComplete="new-password"
                autoFocus
                className="mt-1 block w-full rounded-md border border-zinc-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
              />
            </label>
            <label className="block">
              <span className="text-xs font-medium text-zinc-700">새 비밀번호 확인</span>
              <input
                type="password"
                value={pw2}
                onChange={(e) => setPw2(e.target.value)}
                required
                minLength={MIN_LEN}
                autoComplete="new-password"
                className="mt-1 block w-full rounded-md border border-zinc-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
              />
            </label>

            {err && (
              <div className="rounded-md bg-red-50 px-3 py-2 text-xs text-red-700 ring-1 ring-inset ring-red-200">
                {err}
              </div>
            )}

            <div className="flex gap-2 pt-1">
              <Button
                type="button"
                variant="secondary"
                onClick={onClose}
                disabled={busy}
                className="flex-1"
              >
                취소
              </Button>
              <Button
                type="submit"
                disabled={busy || !pw1 || !pw2}
                className="flex-1"
              >
                {busy ? '변경 중…' : '변경'}
              </Button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
