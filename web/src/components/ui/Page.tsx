import { ReactNode } from 'react';

export function Page({ children, max = '4xl' }: { children: ReactNode; max?: '2xl' | '3xl' | '4xl' | '5xl' | '6xl' }) {
  const maxW = {
    '2xl': 'max-w-2xl',
    '3xl': 'max-w-3xl',
    '4xl': 'max-w-4xl',
    '5xl': 'max-w-5xl',
    '6xl': 'max-w-6xl',
  }[max];
  return <main className={`mx-auto ${maxW} px-6 py-8 space-y-6`}>{children}</main>;
}

export function PageHeader({
  title,
  subtitle,
  right,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  right?: ReactNode;
}) {
  return (
    <div className="flex items-end justify-between gap-4">
      <div className="space-y-0.5">
        <h1 className="text-2xl font-semibold tracking-tight text-zinc-900">{title}</h1>
        {subtitle && <p className="text-sm text-zinc-500">{subtitle}</p>}
      </div>
      {right && <div className="flex items-center gap-2">{right}</div>}
    </div>
  );
}
