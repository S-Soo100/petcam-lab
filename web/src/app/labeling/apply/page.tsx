'use client';

// 라벨러 참여 신청 — 로그인은 했지만 아직 신청 row 가 없는 사용자용(§4.3).
//
// - Auth 이메일은 읽기 전용으로 보여준다(서버가 신뢰하는 값).
// - 이름만 입력받아 POST /api/labeler-applications.
// - 성공하면 접근 상태를 갱신하고 /labeling/pending 으로 이동.
//
// 이 경로는 레이아웃이 unregistered 사용자에게만 허용하므로, 여기 도달했다는 건
// 로그인 + 신청 없음 상태다.

import { FormEvent, useState } from 'react';
import { useRouter } from 'next/navigation';

import { ApiError, applyForLabeling } from '@/lib/labelingApi';
import Button from '@/components/ui/Button';
import { Card, CardTitle } from '@/components/ui/Card';
import { useLabelingAccess } from '../_owner-context';

export default function ApplyPage() {
  const router = useRouter();
  const { access, refresh } = useLabelingAccess();
  const [name, setName] = useState(access?.display_name ?? '');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const displayName = name.trim();
    if (displayName.length < 1 || displayName.length > 80) {
      setErr('이름은 공백을 제외하고 1~80자여야 해.');
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      await applyForLabeling(displayName);
      refresh(); // 레이아웃이 pending 으로 재판정하도록 접근 상태 무효화
      router.replace('/labeling/pending');
    } catch (cause) {
      setBusy(false);
      setErr(
        cause instanceof ApiError ? cause.message : (cause as Error).message,
      );
    }
  }

  return (
    <main className="mx-auto max-w-md px-6 py-16">
      <Card padding="lg">
        <CardTitle>라벨러 참여 신청</CardTitle>
        <p className="mt-1 text-xs text-zinc-500">
          관리자 승인 후 라벨링 큐와 영상에 접근할 수 있어.
        </p>

        <form className="mt-5 space-y-3" onSubmit={handleSubmit}>
          <label className="block">
            <span className="text-xs font-medium text-zinc-700">이메일</span>
            <input
              type="email"
              value={access?.email ?? ''}
              readOnly
              disabled
              className="mt-1 block w-full cursor-not-allowed rounded-md border border-zinc-200 bg-zinc-50 px-3 py-2 text-sm text-zinc-500"
            />
          </label>
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

          {err && (
            <div className="rounded-md bg-red-50 px-3 py-2 text-xs text-red-700 ring-1 ring-inset ring-red-200">
              {err}
            </div>
          )}

          <Button
            type="submit"
            disabled={busy || !name}
            className="w-full"
            size="lg"
          >
            {busy ? '신청 중…' : '참여 신청'}
          </Button>
        </form>
      </Card>
    </main>
  );
}
