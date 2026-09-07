// web/src/lib/labelingV4Server.ts — 목록 row 매퍼·필터 파서(fail-closed).
import 'server-only';

import type { V4ClipItem, V4HighlightState, V4LabelState, V4Scope } from './labelingV4';

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const DEFAULT_LIMIT = 30;
const MAX_LIMIT = 100;

export interface V4ListRequest {
  scope: V4Scope;
  cameraIds: string[] | null;
  labelState: V4LabelState | null;
  highlightState: V4HighlightState | null;
  limit: number;
}

// 허용 값 외에는 전부 throw — route 가 400 으로 매핑한다(DB 호출 전 차단).
export function parseV4ListRequest(sp: URLSearchParams): V4ListRequest {
  const scope = sp.get('scope');
  if (scope !== 'mine' && scope !== 'all') throw new Error('invalid_scope');
  const cameraIds = sp.getAll('camera_id');
  for (const id of cameraIds) if (!UUID_RE.test(id)) throw new Error('invalid_camera_id');
  const labelState = sp.get('label_state');
  if (labelState !== null && labelState !== 'unlabeled' && labelState !== 'labeled') throw new Error('invalid_label_state');
  const highlightState = sp.get('highlight_state');
  if (highlightState !== null && !['yes', 'no', 'pending'].includes(highlightState)) throw new Error('invalid_highlight_state');
  const rawLimit = sp.get('limit');
  const limit = rawLimit === null ? DEFAULT_LIMIT : Number(rawLimit);
  if (!Number.isInteger(limit) || limit < 1 || limit > MAX_LIMIT) throw new Error('invalid_limit');
  return {
    scope,
    cameraIds: cameraIds.length ? cameraIds : null,
    labelState: labelState as V4LabelState | null,
    highlightState: highlightState as V4HighlightState | null,
    limit,
  };
}

export interface V4ClipRow {
  clip_id: unknown; camera_id: unknown; camera_name: unknown; started_at: unknown; duration_sec: unknown;
  media_ready: unknown; highlight_source: unknown; highlight_status: unknown; highlight_value: unknown;
  highlight_reason: unknown; reviewer_name: unknown; decided_at: unknown;
}

// fn_list_labeling_v4_clips 행 → 공개 항목. 모르는 source/status 는 fail-closed.
export function mapV4ClipRow(row: V4ClipRow): V4ClipItem {
  if (typeof row.clip_id !== 'string' || typeof row.started_at !== 'string' || typeof row.camera_name !== 'string') throw new Error('invalid_v4_clip_row');
  if (row.highlight_source !== 'human' && row.highlight_source !== 'rule') throw new Error('invalid_v4_clip_row');
  if (!['decided', 'pending', 'failed'].includes(row.highlight_status as string)) throw new Error('invalid_v4_clip_row');
  if (row.highlight_value !== null && typeof row.highlight_value !== 'boolean') throw new Error('invalid_v4_clip_row');
  return {
    id: row.clip_id,
    camera_id: typeof row.camera_id === 'string' ? row.camera_id : null,
    camera_name: row.camera_name,
    started_at: row.started_at,
    duration_sec: typeof row.duration_sec === 'number' ? row.duration_sec : row.duration_sec === null ? null : Number(row.duration_sec),
    media_ready: Boolean(row.media_ready),
    highlight: {
      source: row.highlight_source,
      status: row.highlight_status as V4ClipItem['highlight']['status'],
      value: row.highlight_value as boolean | null,
      reason: typeof row.highlight_reason === 'string' ? row.highlight_reason : '',
      reviewer_name: typeof row.reviewer_name === 'string' ? row.reviewer_name : null,
      decided_at: typeof row.decided_at === 'string' ? row.decided_at : null,
    },
  };
}
