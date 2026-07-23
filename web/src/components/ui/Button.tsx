import { ButtonHTMLAttributes, ReactNode } from 'react';

type Variant =
  | 'primary'
  | 'secondary'
  | 'ghost'
  | 'danger'
  | 'labelingPrimary'
  | 'labelingSecondary'
  | 'labelingDanger';
type Size = 'sm' | 'md' | 'lg';

// 라벨링 작업 전용 focus ring — 세 labeling variant 공용(설계 §4.6·접근성 §9).
const LABELING_FOCUS =
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500 focus-visible:ring-offset-2';

const VARIANT: Record<Variant, string> = {
  // 기존 variant 는 로그인·회원관리·일반 내비게이션이 쓰므로 byte-equivalent 로 보존한다(설계 §4.6).
  primary:
    'bg-zinc-900 text-white hover:bg-zinc-800 disabled:bg-zinc-400 disabled:hover:bg-zinc-400',
  secondary:
    'border border-zinc-300 bg-white text-zinc-800 hover:bg-zinc-50 disabled:opacity-50',
  ghost: 'text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900 disabled:opacity-50',
  danger:
    'bg-red-600 text-white hover:bg-red-700 disabled:bg-red-300 disabled:hover:bg-red-300',
  // 라벨링 작업 화면 CTA — 검은색 대신 진한 초록. 최소 높이 44px.
  labelingPrimary: `min-h-11 bg-emerald-700 text-white shadow-sm hover:bg-emerald-800 disabled:bg-zinc-200 disabled:text-zinc-500 ${LABELING_FOCUS}`,
  labelingSecondary: `min-h-11 border-2 border-zinc-300 bg-white text-zinc-800 shadow-sm hover:border-zinc-500 hover:bg-zinc-50 disabled:border-zinc-200 disabled:bg-zinc-100 disabled:text-zinc-400 ${LABELING_FOCUS}`,
  labelingDanger: `min-h-11 border-2 border-rose-500 bg-white text-rose-800 shadow-sm hover:bg-rose-50 disabled:border-zinc-200 disabled:bg-zinc-100 disabled:text-zinc-400 ${LABELING_FOCUS}`,
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
