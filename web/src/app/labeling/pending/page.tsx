'use client';

// 승인 대기 / 거절 안내 화면(§4.4).
//
// - pending: 승인 대기 안내 + 이름·이메일 + 상태 새로고침 + 로그아웃.
// - rejected: 승인되지 않았다는 안내 + 관리자 문의 + 로그아웃.
// - 새로고침 후 owner/labeler 가 되면 레이아웃이 자동으로 /labeling 으로 보낸다.
//
// 접근 상태는 레이아웃이 컨텍스트로 내려준다. '상태 새로고침' 은 컨텍스트의 refresh()
// 로 접근 상태를 다시 조회한다.

import { useState } from 'react';
import { useRouter } from 'next/navigation';

import { getSupabaseBrowser } from '@/lib/supabaseBrowser';
import Button from '@/components/ui/Button';
import { Card, CardTitle } from '@/components/ui/Card';
import { useLabelingAccess } from '../_owner-context';

export default function PendingPage() {
  const router = useRouter();
  const { access, refresh } = useLabelingAccess();
  const [signingOut, setSigningOut] = useState(false);
  const rejected = access?.status === 'rejected';

  async function signOut() {
    setSigningOut(true);
    await getSupabaseBrowser().auth.signOut();
    router.replace('/labeling/login');
  }

  return (
    <main className="mx-auto max-w-md px-6 py-16">
      <Card padding="lg">
        <div className="flex items-center justify-between gap-3">
          <CardTitle>
            {rejected ? '승인되지 않은 계정' : '관리자 승인 대기 중'}
          </CardTitle>
          <span
            className={`rounded-md px-1.5 py-0.5 text-[11px] font-semibold ring-1 ring-inset ${
              rejected
                ? 'bg-red-50 text-red-700 ring-red-200'
                : 'bg-amber-50 text-amber-700 ring-amber-200'
            }`}
          >
            {rejected ? '거절됨' : '대기'}
          </span>
        </div>

        <dl className="mt-4 space-y-2 text-sm">
          {access?.display_name && (
            <div className="flex justify-between gap-3">
              <dt className="text-zinc-500">이름</dt>
              <dd className="font-medium text-zinc-800">
                {access.display_name}
              </dd>
            </div>
          )}
          <div className="flex justify-between gap-3">
            <dt className="text-zinc-500">이메일</dt>
            <dd className="truncate font-medium text-zinc-800">
              {access?.email}
            </dd>
          </div>
        </dl>

        <p className="mt-4 rounded-md bg-zinc-50 px-3 py-2 text-xs text-zinc-600 ring-1 ring-inset ring-zinc-200">
          {rejected
            ? '이 계정은 아직 승인되지 않았어. 접근이 필요하면 관리자에게 문의해.'
            : '가입은 완료됐지만 영상 데이터 접근은 관리자 승인 후에 열려. 승인되면 이 화면에서 자동으로 큐로 넘어가.'}
        </p>

        <div className="mt-5 flex gap-2">
          {!rejected && (
            <Button onClick={refresh} className="flex-1">
              상태 새로고침
            </Button>
          )}
          <Button
            variant="secondary"
            onClick={signOut}
            disabled={signingOut}
            className={rejected ? 'w-full' : 'flex-1'}
          >
            {signingOut ? '로그아웃 중…' : '로그아웃'}
          </Button>
        </div>
      </Card>
    </main>
  );
}
