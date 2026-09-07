// v4 상세 PC 단축키(UX ④, 2026-09-08) — 순수 매핑. 키 이벤트 → 동작 이름. 입력 중이거나 조합키면 무시.
//
// O/X 확정 · 1~5 사유 칩 · Enter 저장하고 다음 · Space 재생/일시정지 · N 다음 움직임 · F 의미있는 행동.
// 게코 미관측 화면에선 O = "게코 보여·하이라이트 O", X = "게코 안 보여·X" 로 같은 키가 매핑된다.

export type HotkeyAction =
  | { kind: 'verdict'; verdict: boolean }
  | { kind: 'reason'; index: number } // 0-based, 칩 목록 순서
  | { kind: 'save' }
  | { kind: 'toggle_play' }
  | { kind: 'next_motion' }
  | { kind: 'toggle_flag' };

export interface HotkeyEventLike {
  key: string;
  ctrlKey?: boolean;
  metaKey?: boolean;
  altKey?: boolean;
  target?: { tagName?: string; isContentEditable?: boolean } | null;
}

const TYPING_TAGS = new Set(['INPUT', 'TEXTAREA', 'SELECT']);

export function isTypingTarget(target: HotkeyEventLike['target']): boolean {
  if (!target) return false;
  if (target.isContentEditable) return true;
  return TYPING_TAGS.has((target.tagName ?? '').toUpperCase());
}

export function mapHotkey(e: HotkeyEventLike): HotkeyAction | null {
  if (e.ctrlKey || e.metaKey || e.altKey) return null;
  if (isTypingTarget(e.target)) return null;
  const k = e.key;
  if (k === 'o' || k === 'O' || k === 'ㅐ') return { kind: 'verdict', verdict: true }; // 한글 자판 O 자리
  if (k === 'x' || k === 'X' || k === 'ㅌ') return { kind: 'verdict', verdict: false };
  if (k >= '1' && k <= '5') return { kind: 'reason', index: Number(k) - 1 };
  if (k === 'Enter') return { kind: 'save' };
  if (k === ' ' || k === 'Spacebar') return { kind: 'toggle_play' };
  if (k === 'n' || k === 'N' || k === 'ㅜ') return { kind: 'next_motion' };
  if (k === 'f' || k === 'F' || k === 'ㄹ') return { kind: 'toggle_flag' };
  return null;
}

export const HOTKEY_LEGEND = 'O / X 확정 · 1~5 사유 · Enter 저장 · Space 재생 · N 다음 움직임 · F 의미있는 행동';
