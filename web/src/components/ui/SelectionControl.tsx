import { ButtonHTMLAttributes, ReactNode } from 'react';

// 라벨링 작업 화면 공통 선택 컨트롤(설계 §4.6). 검은 active 채움을 쓰지 않고, 선택 상태를
// 의미색 배경 + 2px 테두리 + 체크(✓) + 보이는 '선택됨' 텍스트 + aria-pressed 로 중복 표현한다.
// 색을 구분하지 못해도 무엇이 선택됐는지 확신하게 한다(접근성 §9).

export type SelectionTone = 'success' | 'warning' | 'danger' | 'neutral';

// 선택된 상태의 의미색. label→success, hold→warning, exclude→danger, 필터/날짜/카메라→neutral.
const SELECTED_TONE: Record<SelectionTone, string> = {
  success: 'border-emerald-600 bg-emerald-50 text-emerald-950',
  warning: 'border-amber-500 bg-amber-50 text-amber-950',
  danger: 'border-rose-500 bg-rose-50 text-rose-950',
  neutral: 'border-sky-500 bg-sky-50 text-sky-950',
};

// 상태 무관 공통 — 최소 높이 44px(min-h-11), 키보드 focus ring, 비활성 대비.
const BASE =
  'min-h-11 border-2 font-medium transition-colors ' +
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500 focus-visible:ring-offset-2 ' +
  'disabled:cursor-not-allowed disabled:border-zinc-200 disabled:bg-zinc-100 disabled:text-zinc-400 disabled:shadow-none';

// 누를 수 있음(선택 안 됨) — 흰 배경, 중립 테두리, 약한 그림자, hover.
const IDLE = 'border-zinc-300 bg-white text-zinc-800 shadow-sm hover:border-zinc-500 hover:bg-zinc-50';

function stateClasses(pressed: boolean, tone: SelectionTone): string {
  return pressed ? `${SELECTED_TONE[tone]} shadow-sm` : IDLE;
}

export interface SelectionChipProps
  extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'aria-pressed'> {
  pressed: boolean;
  tone: SelectionTone;
  children: ReactNode;
}

// 필터·날짜·카메라·상태 탭용 pill.
export function SelectionChip({
  pressed,
  tone,
  className = '',
  children,
  type,
  ...rest
}: SelectionChipProps) {
  return (
    <button
      {...rest}
      type={type ?? 'button'}
      aria-pressed={pressed}
      className={`${BASE} ${stateClasses(pressed, tone)} inline-flex items-center gap-1.5 rounded-full px-3.5 py-1.5 text-sm ${className}`}
    >
      {pressed && <span aria-hidden="true">✓</span>}
      <span>{children}</span>
      {pressed && <span className="text-[10px] font-semibold">선택됨</span>}
    </button>
  );
}

export interface SelectionCardProps
  extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'aria-pressed' | 'title'> {
  pressed: boolean;
  tone: SelectionTone;
  title: string;
  description: string;
}

// 판정 CTA·선택 카드용 — 제목 + 설명을 담은 전체 클릭 카드.
export function SelectionCard({
  pressed,
  tone,
  title,
  description,
  className = '',
  type,
  ...rest
}: SelectionCardProps) {
  return (
    <button
      {...rest}
      type={type ?? 'button'}
      aria-pressed={pressed}
      className={`${BASE} ${stateClasses(pressed, tone)} flex w-full flex-col items-start gap-1 rounded-xl px-4 py-3 text-left ${className}`}
    >
      <span className="flex items-center gap-2 text-sm font-semibold">
        {pressed && <span aria-hidden="true">✓</span>}
        <span>{title}</span>
        {pressed && <span className="text-[10px] font-semibold">선택됨</span>}
      </span>
      <span className="text-xs font-normal">{description}</span>
    </button>
  );
}
