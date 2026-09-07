// 하이라이트 v4 공개 계약(클라이언트/서버 공용, 순수). run id·detector identity·reviewer UUID 는 없다.

export type HighlightInitialStatus = 'decided' | 'pending' | 'failed';
export type HighlightSource = 'human' | 'rule';
export type HighlightVerdictKind = 'initial' | 'correction';

export const HIGHLIGHT_TRIGGERS = ['long_activity', 'sustained_move', 'frequent_bursts', 'early_action'] as const;
export type HighlightTrigger = (typeof HIGHLIGHT_TRIGGERS)[number];

export const HIGHLIGHT_CHANGE_REASONS = [
  'false_detection', 'gecko_not_visible', 'camera_shake', 'too_short', 'interesting_low_numbers', 'other',
] as const;
export type HighlightChangeReason = (typeof HIGHLIGHT_CHANGE_REASONS)[number];

export const HIGHLIGHT_CHANGE_REASON_LABELS: Record<HighlightChangeReason, string> = {
  false_detection: '오검출',
  gecko_not_visible: '게코 안 보임',
  camera_shake: '카메라 흔들림',
  too_short: '움직임 짧음',
  interesting_low_numbers: '재밌는데 숫자 낮음',
  other: '기타',
};

// 칩 아래·툴팁에 보이는 한 줄 설명(2026-09-08 owner 피드백 "이유가 너무 짧게 설명돼"). 규칙 O → 사람 X 사유.
export const HIGHLIGHT_CHANGE_REASON_DESCRIPTIONS: Record<HighlightChangeReason, string> = {
  false_detection: '움직임으로 잡혔지만 게코 움직임이 아니야 (그림자·빛 변화·벌레·노이즈).',
  gecko_not_visible: '영상에 게코가 아예 안 보여.',
  camera_shake: '카메라나 케이지가 흔들려서 움직임으로 잡혔어.',
  too_short: '게코가 움직이긴 했지만 짧고 사소해서 하이라이트는 아니야.',
  interesting_low_numbers: '숫자는 낮은데 볼만한 행동이야.',
  other: '위에 없는 이유. 규칙 조정 때 참고만 해.',
};

export const HIGHLIGHT_TRIGGER_LABELS: Record<HighlightTrigger, string> = {
  long_activity: '오래 움직임',
  sustained_move: '연속 이동',
  frequent_bursts: '잦은 움직임',
  early_action: '촬영 직후 움직임',
};

export interface HighlightFeatures {
  activity_sec: number;
  longest_moving_sec: number;
  moving_burst_count: number;
  first_moving_sec: number | null;
  // 게코가 관측된 시간. 0 이면 규칙이 "게코 미관측"으로 X 를 낸다(구버전 응답엔 없을 수 있어 null 허용).
  visible_sec: number | null;
}

export interface HighlightInitial {
  status: HighlightInitialStatus;
  value: boolean | null; // decided 일 때만 boolean
  rule_version: string;
  reason: string;
  fired: HighlightTrigger[];
  shadow: HighlightTrigger[];
  features: HighlightFeatures | null;
}

// 1차 판정이 "게코 미관측" X 인가 — 이 경우 O/X 버튼 대신 "게코 안 보여 / 게코 보여" 로 묻는다(2026-09-08 owner 피드백).
// features.visible_sec 이 있으면 그걸로, 없으면 규칙이 내는 고정 사유 문구로 판별한다.
export function isGeckoNotObserved(initial: Pick<HighlightInitial, 'status' | 'value' | 'reason' | 'features'>): boolean {
  if (initial.status !== 'decided' || initial.value !== false) return false;
  const visible = initial.features?.visible_sec;
  if (typeof visible === 'number') return visible <= 0;
  return initial.reason === '게코 미관측';
}

export interface HighlightCurrent {
  source: HighlightSource;
  status: HighlightInitialStatus;
  value: boolean | null;
  rule_version: string;
  reason: string;
  reviewer_name: string | null;
  decided_at: string | null;
  verdict_kind: HighlightVerdictKind | null;
}

export interface HighlightDetail {
  current: HighlightCurrent;
  initial: HighlightInitial;
}

export interface HighlightVerdictInput {
  verdict: boolean;
  change_reason?: HighlightChangeReason | null;
}

export interface HighlightVerdictResult {
  verdict_id: string;
  initial: boolean | null;
  changed: boolean | null;
  rule_version: string;
}

export function highlightValueLabel(value: boolean | null, status: HighlightInitialStatus): string {
  if (status === 'pending') return '분석 대기';
  if (status === 'failed') return '분석 실패';
  return value ? '하이라이트 O' : '하이라이트 X';
}

export function isHighlightChangeReason(v: unknown): v is HighlightChangeReason {
  return typeof v === 'string' && (HIGHLIGHT_CHANGE_REASONS as readonly string[]).includes(v);
}
