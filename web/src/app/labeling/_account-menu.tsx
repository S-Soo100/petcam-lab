'use client';

// 계정 보조 메뉴 — 이메일 표시 + 비밀번호 변경 + 로그아웃(설계 §3.3·§9).
//
// 업무 내비게이션과 분리된 컴팩트 드롭다운. 320px 에서도 헤더가 줄바꿈되지 않게 이메일은
// truncate(전체 이름은 title 로), 트리거는 whitespace-nowrap 으로 한 줄을 유지한다.

import { useState } from 'react';

export default function AccountMenu({
  email,
  onChangePassword,
  onSignOut,
}: {
  email: string;
  onChangePassword: () => void;
  onSignOut: () => void;
}) {
  const [open, setOpen] = useState(false);

  return (
    <div className="relative flex min-w-0 items-center">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex min-w-0 items-center gap-1 whitespace-nowrap rounded-md px-2 py-1 text-xs text-zinc-600 hover:bg-zinc-100"
        aria-haspopup="menu"
        aria-expanded={open}
      >
        <span className="max-w-[9rem] truncate" title={email || '계정'}>
          {email || '계정'}
        </span>
        <span aria-hidden>▾</span>
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 top-full z-50 mt-1 w-40 rounded-md border border-zinc-200 bg-white p-1 shadow-lg"
        >
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setOpen(false);
              onChangePassword();
            }}
            className="block w-full whitespace-nowrap rounded px-3 py-1.5 text-left text-sm text-zinc-700 hover:bg-zinc-100"
          >
            비밀번호 변경
          </button>
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setOpen(false);
              onSignOut();
            }}
            className="block w-full whitespace-nowrap rounded px-3 py-1.5 text-left text-sm text-zinc-700 hover:bg-zinc-100"
          >
            로그아웃
          </button>
        </div>
      )}
    </div>
  );
}
