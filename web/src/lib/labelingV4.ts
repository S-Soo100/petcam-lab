// web/src/lib/labelingV4.ts — v4 공개 계약(순수).
import type { HighlightDetail, HighlightInitialStatus, HighlightSource } from './highlightV4';

export type V4Scope = 'mine' | 'all';
export type V4LabelState = 'unlabeled' | 'labeled';
export type V4HighlightState = 'yes' | 'no' | 'pending';

export interface V4ClipHighlight {
  source: HighlightSource;
  status: HighlightInitialStatus;
  value: boolean | null;
  reason: string;
  reviewer_name: string | null;
  decided_at: string | null;
}

export interface V4ClipItem {
  id: string;
  camera_id: string | null;
  camera_name: string;
  started_at: string;
  duration_sec: number | null;
  media_ready: boolean;
  highlight: V4ClipHighlight;
}

export interface V4ClipListResponse {
  items: V4ClipItem[];
  next_cursor: string | null;
  has_more: boolean;
}

export interface V4ListFilters {
  scope: V4Scope;
  cameraIds?: string[];
  labelState?: V4LabelState | null;
  highlightState?: V4HighlightState | null;
  cursor?: string | null;
  limit?: number;
}

export interface V4ClipDetail {
  id: string;
  camera_id: string | null;
  started_at: string;
  duration_sec: number | null;
  media_ready: boolean;
  highlight: HighlightDetail;
}

export interface V4CameraOption { id: string; name: string; assigned: boolean }

export interface V4Member { user_id: string; display_name: string; camera_ids: string[] }

export interface V4Overview {
  activity_day: string | null;
  unlabeled_total: number;
  labeled_today: number;
  labeled_7d: number;
  members: { user_id: string; display_name: string; labeled_7d: number }[]; // owner 전용 화면 — UUID 노출 OK
  cameras: { camera_name: string; unlabeled: number; labeled_7d: number }[];
}

export const V4_LABEL_STATE_LABELS: Record<V4LabelState, string> = { unlabeled: '라벨 안 됨', labeled: '라벨 됨' };
export const V4_HIGHLIGHT_STATE_LABELS: Record<V4HighlightState, string> = { yes: '하이라이트 O', no: '하이라이트 X', pending: '분석 대기' };

export function v4DetailPath(clipId: string): string {
  return `/labeling/v4/${clipId}`;
}
