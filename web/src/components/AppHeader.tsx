'use client';
import Link from 'next/link';
import { usePathname } from 'next/navigation';

const NAV = [
  { href: '/', label: '대시보드' },
  { href: '/upload', label: 'F1 업로드' },
  { href: '/queue', label: 'F2 라벨' },
  { href: '/inference', label: 'F3 추론' },
  { href: '/results', label: '결과' },
];

export default function AppHeader() {
  const pathname = usePathname();
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
      </div>
    </header>
  );
}
