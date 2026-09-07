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
  too_short: '너무 짧음',
  interesting_low_numbers: '재밌는데 숫자 낮음',
  other: '기타',
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
