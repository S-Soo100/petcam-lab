'use client';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useEffect, useRef, useState } from 'react';

const NAV = [
  { href: '/', label: '대시보드' },
  { href: '/upload', label: 'F1 업로드' },
  { href: '/queue', label: 'F2 라벨' },
  { href: '/inference', label: 'F3 추론' },
  { href: '/results', label: '결과' },
];

export default function AppHeader() {
  const pathname = usePathname();
  const router = useRouter();
  const [refreshing, setRefreshing] = useState(false);
  const [lastRefresh, setLastRefresh] = useState<number>(Date.now());

  function refresh() {
    setRefreshing(true);
    router.refresh();
    setLastRefresh(Date.now());
    // router.refresh()는 동기 트리거지만 실제 fetch는 비동기. 짧은 시각 피드백만.
    setTimeout(() => setRefreshing(false), 400);
  }

  // 탭 다시 활성화될 때 자동 새로고침 (다른 탭/Supabase 콘솔 갔다 오면 fresh data)
  useEffect(() => {
    function onVisible() {
      if (document.visibilityState === 'visible') {
        router.refresh();
        setLastRefresh(Date.now());
      }
    }
    document.addEventListener('visibilitychange', onVisible);
    return () => document.removeEventListener('visibilitychange', onVisible);
  }, [router]);

  // 페이지 이동 시 router cache 우회 (첫 마운트는 server에서 fresh이므로 skip)
  const mounted = useRef(false);
  useEffect(() => {
    if (!mounted.current) {
      mounted.current = true;
      return;
    }
    router.refresh();
    setLastRefresh(Date.now());
  }, [pathname, router]);

  return (
    <header className="sticky top-0 z-30 border-b border-zinc-200 bg-white/80 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center gap-6 px-6 py-3">
        <Link href="/" className="flex items-center gap-2">
          <span className="grid h-7 w-7 place-items-center rounded-md bg-zinc-900 text-xs font-semibold text-white">
            VL
          </span>
          <span className="text-sm font-semibold tracking-tight text-zinc-900">
            VLM PoC
            <span className="ml-1.5 font-normal text-zinc-500">/ Round 1</span>
          </span>
        </Link>
        <nav className="flex items-center gap-1 text-sm">
          {NAV.map((n) => {
            const active =
              n.href === '/' ? pathname === '/' : pathname?.startsWith(n.href);
            return (
              <Link
                key={n.href}
                href={n.href}
                prefetch={false}
                className={`rounded-md px-3 py-1.5 transition-colors ${
                  active
                    ? 'bg-zinc-900 text-white'
                    : 'text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900'
                }`}
              >
                {n.label}
              </Link>
            );
          })}
        </nav>
        <div className="ml-auto flex items-center gap-3 text-xs text-zinc-500">
          <span className="tabular-nums">
            {new Date(lastRefresh).toLocaleTimeString('ko-KR', { hour12: false })}
          </span>
          <button
            onClick={refresh}
            disabled={refreshing}
            title="DB에서 새로 가져오기"
            className="flex items-center gap-1.5 rounded-md border border-zinc-200 bg-white px-2.5 py-1 font-medium text-zinc-700 hover:bg-zinc-50 disabled:opacity-50"
          >
            <span className={refreshing ? 'animate-spin' : ''}>↻</span>
            <span>새로고침</span>
          </button>
        </div>
      </div>
    </header>
  );
}
