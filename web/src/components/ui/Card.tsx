import { ReactNode } from 'react';

export function Card({
  children,
  className = '',
  padding = 'md',
}: {
  children: ReactNode;
  className?: string;
  padding?: 'none' | 'sm' | 'md' | 'lg';
}) {
  const pad =
    padding === 'none' ? '' : padding === 'sm' ? 'p-3' : padding === 'lg' ? 'p-6' : 'p-5';
  return (
    <div className={`rounded-xl border border-zinc-200 bg-white shadow-sm ${pad} ${className}`}>
      {children}
    </div>
  );
}

export function CardTitle({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <h2 className={`text-sm font-semibold tracking-tight text-zinc-900 ${className}`}>{children}</h2>
  );
}
