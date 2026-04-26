import { ButtonHTMLAttributes, ReactNode } from 'react';

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger';
type Size = 'sm' | 'md' | 'lg';

const VARIANT: Record<Variant, string> = {
  primary:
    'bg-zinc-900 text-white hover:bg-zinc-800 disabled:bg-zinc-400 disabled:hover:bg-zinc-400',
  secondary:
    'border border-zinc-300 bg-white text-zinc-800 hover:bg-zinc-50 disabled:opacity-50',
  ghost: 'text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900 disabled:opacity-50',
  danger:
    'bg-red-600 text-white hover:bg-red-700 disabled:bg-red-300 disabled:hover:bg-red-300',
};

const SIZE: Record<Size, string> = {
  sm: 'px-2.5 py-1 text-xs',
  md: 'px-3.5 py-1.5 text-sm',
  lg: 'px-5 py-2.5 text-sm',
};

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  children: ReactNode;
}

export default function Button({
  variant = 'primary',
  size = 'md',
  className = '',
  children,
  ...rest
}: Props) {
  return (
    <button
      {...rest}
      className={`inline-flex items-center justify-center rounded-md font-medium transition-colors disabled:cursor-not-allowed ${VARIANT[variant]} ${SIZE[size]} ${className}`}
    >
      {children}
    </button>
  );
}
