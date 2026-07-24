'use client';

// 미승인 사용자 참여 상태 화면(설계 §3.3). 단일 참여 화면 — 업무 내비게이션은 없다(RoleShell 이
// 미승인 역할엔 nav 를 렌더하지 않음). 비밀번호 변경·로그아웃은 셸 상단 계정 메뉴로만 접근한다.
//
// - pending: 승인 대기 안내 + 이름·이메일 + 다음 행동 한 가지(상태 새로고침).
// - rejected: 승인되지 않았다는 안내 + 관리자 문의(다음 행동은 관리자 대응 대기).
// - 새로고침 후 owner/labeler 가 되면 레이아웃이 자동으로 역할 홈으로 보낸다.

import Button from '@/components/ui/Button';
import { Card, CardTitle } from '@/components/ui/Card';
import { useLabelingAccess } from '../_owner-context';

export default function PendingPage() {
  const { access, refresh } = useLabelingAccess();
  const rejected = access?.status === 'rejected';

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
            : '가입은 완료됐지만 영상 데이터 접근은 관리자 승인 후에 열려. 승인 안내를 받으면 상태 새로고침을 눌러줘.'}
        </p>

        {/* 다음 행동 한 가지. 로그아웃·비밀번호 변경은 상단 계정 메뉴(셸)로 진입한다(설계 §3.3). */}
        <div className="mt-5">
          {rejected ? (
            <p className="text-xs text-zinc-500">접근이 필요하면 관리자에게 문의해.</p>
          ) : (
            <Button onClick={refresh} className="w-full">
              상태 새로고침
            </Button>
          )}
        </div>
      </Card>
    </main>
  );
}
