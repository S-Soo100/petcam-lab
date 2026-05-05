'use client';

// 가벼운 자체 Toast — 디펜던시 추가 안 하고 50줄로 끝나는 구현.
//
// 왜 외부 lib (sonner / react-hot-toast) 안 쓰나?
// - 라벨링 저장 알림 정도가 유일 use-case. 1개 lib 더 들이는 비용 > 자체 구현.
// - sonner 가 표준이긴 한데 dedup / animation / queue stack 같은 고급 기능 불필요.
//
// 왜 Provider 가 RootLayout 에 있나?
// - save() 가 router.push(back) 으로 즉시 다른 페이지(/queue 등) 이동.
// - Provider 가 /labeling layout 에 있으면 페이지 전환 시 unmount → toast 못 봄.
// - root layout 에 두면 페이지 바뀌어도 살아있고 자동 dismiss timer 도 정상 작동.
//
// React Context 설계:
// - Server Component (RootLayout) 안에 'use client' Provider 둘 수 있음 (Next.js 표준).
// - children prop 으로 하위 server/client tree 를 그대로 통과.

import { createContext, useCallback, useContext, useState } from 'react';

type Kind = 'success' | 'error' | 'info';

interface ToastItem {
  id: number;
  msg: string;
  kind: Kind;
}

interface ToastApi {
  show: (msg: string, kind?: Kind) => void;
}

const ToastCtx = createContext<ToastApi | null>(null);

export function useToast(): ToastApi {
  const ctx = useContext(ToastCtx);
  // RootLayout 안에 항상 박혀있어 null 일 일은 사실상 없지만, 개발 중 잘못 import
  // 했을 때 silent fail 보다 throw 가 낫다.
  if (!ctx) throw new Error('useToast must be used inside <ToastProvider>');
  return ctx;
}

const DISMISS_MS = 2200;

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);

  const show = useCallback((msg: string, kind: Kind = 'success') => {
    // Date.now() + Math.random() — 동시 다발 호출 시 id 중복 방지.
    const id = Date.now() + Math.random();
    setItems((arr) => [...arr, { id, msg, kind }]);
    setTimeout(() => {
      setItems((arr) => arr.filter((t) => t.id !== id));
    }, DISMISS_MS);
  }, []);

  return (
    <ToastCtx.Provider value={{ show }}>
      {children}
      {/* pointer-events-none on container, pointer-events-auto on item — 클릭 통과 */}
      <div className="pointer-events-none fixed bottom-6 right-6 z-50 flex flex-col gap-2">
        {items.map((t) => (
          <div
            key={t.id}
            role="status"
            aria-live="polite"
            className={`pointer-events-auto rounded-lg px-4 py-2.5 text-sm font-medium shadow-lg ring-1 ring-black/5 ${
              t.kind === 'success'
                ? 'bg-emerald-600 text-white'
                : t.kind === 'error'
                  ? 'bg-red-600 text-white'
                  : 'bg-zinc-900 text-white'
            }`}
          >
            {t.msg}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}
