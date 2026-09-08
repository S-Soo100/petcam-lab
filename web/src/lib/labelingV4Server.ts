// web/src/lib/labelingV4Server.ts — 목록 row 매퍼·필터 파서(fail-closed).
import 'server-only';

import { EVAL_SAMPLE_ID_RE, type V4BehaviorFlagFilter, type V4ClipItem, type V4HighlightState, type V4LabelState, type V4Scope } from './labelingV4';
import { UUID_RE } from '@/lib/uuid';

const DEFAULT_LIMIT = 30;
const MAX_LIMIT = 100;

export interface V4ListRequest {
  scope: V4Scope;
  cameraIds: string[] | null;
  labelState: V4LabelState | null;
  highlightState: V4HighlightState | null;
  behaviorFlag: V4BehaviorFlagFilter | null;
  sampleId: string | null;
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
  const behaviorFlag = sp.get('behavior_flag');
  if (behaviorFlag !== null && behaviorFlag !== 'yes') throw new Error('invalid_behavior_flag');
  const sample = sp.get('sample');
  if (sample !== null && !EVAL_SAMPLE_ID_RE.test(sample)) throw new Error('invalid_sample');
  const rawLimit = sp.get('limit');
  const limit = rawLimit === null ? DEFAULT_LIMIT : Number(rawLimit);
  if (!Number.isInteger(limit) || limit < 1 || limit > MAX_LIMIT) throw new Error('invalid_limit');
  return {
    scope,
    cameraIds: cameraIds.length ? cameraIds : null,
    labelState: labelState as V4LabelState | null,
    highlightState: highlightState as V4HighlightState | null,
    behaviorFlag: behaviorFlag as V4BehaviorFlagFilter | null,
    sampleId: sample,
    limit,
  };
}

export interface V4ClipRow {
  clip_id: unknown; camera_id: unknown; camera_name: unknown; started_at: unknown; duration_sec: unknown;
  media_ready: unknown; highlight_source: unknown; highlight_status: unknown; highlight_value: unknown;
  highlight_reason: unknown; reviewer_id: unknown; reviewer_display_name: unknown; decided_at: unknown;
  behavior_flagged: unknown; behavior_flagged_by: unknown; behavior_flagged_by_display_name: unknown; behavior_flagged_at: unknown;
}

export interface BehaviorFlagRow { flagged: unknown; flagged_by: unknown; flagged_by_display_name: unknown; flagged_at: unknown }

// fn_get/set_motion_clip_behavior_flag 행 → 공개 값. flagged_by UUID 는 표시명으로만 접는다.
export function mapBehaviorFlagRow(row: BehaviorFlagRow, resolveName: ReviewerNameResolver): V4ClipItem['behavior_flag'] {
  if (row.flagged !== true) return { flagged: false, flagged_by_name: null, flagged_at: null };
  if (typeof row.flagged_by !== 'string' || !UUID_RE.test(row.flagged_by)) throw new Error('invalid_behavior_flag_row');
  return {
    flagged: true,
    flagged_by_name: resolveName(row.flagged_by, typeof row.flagged_by_display_name === 'string' ? row.flagged_by_display_name : null),
    flagged_at: typeof row.flagged_at === 'string' ? row.flagged_at : null,
  };
}

// 표시명 해석기 — route 가 resolveReviewerName(_access) 을 넘긴다. 이 lib 은 순수하게 둔다.
export type ReviewerNameResolver = (reviewerId: string, displayName: string | null) => string;

// fn_list_labeling_v4_clips 행 → 공개 항목. 모르는 source/status 는 fail-closed.
// reviewer_id·raw display_name 은 표시명으로만 바꾸고 공개 JSON 에서 뺀다(라벨러에게 UUID 비노출).
export function mapV4ClipRow(row: V4ClipRow, resolveName: ReviewerNameResolver): V4ClipItem {
  if (typeof row.clip_id !== 'string' || typeof row.started_at !== 'string' || typeof row.camera_name !== 'string') throw new Error('invalid_v4_clip_row');
  if (row.highlight_source !== 'human' && row.highlight_source !== 'rule') throw new Error('invalid_v4_clip_row');
  if (!['decided', 'pending', 'failed'].includes(row.highlight_status as string)) throw new Error('invalid_v4_clip_row');
  if (row.highlight_value !== null && typeof row.highlight_value !== 'boolean') throw new Error('invalid_v4_clip_row');
  if (row.highlight_source === 'human' && (typeof row.reviewer_id !== 'string' || !UUID_RE.test(row.reviewer_id))) throw new Error('invalid_v4_clip_row');
  const reviewerName = row.highlight_source === 'human'
    ? resolveName(row.reviewer_id as string, typeof row.reviewer_display_name === 'string' ? row.reviewer_display_name : null)
    : null;
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
      reviewer_name: reviewerName,
      decided_at: typeof row.decided_at === 'string' ? row.decided_at : null,
    },
    behavior_flag: mapBehaviorFlagRow(
      { flagged: row.behavior_flagged, flagged_by: row.behavior_flagged_by, flagged_by_display_name: row.behavior_flagged_by_display_name, flagged_at: row.behavior_flagged_at },
      resolveName,
    ),
    thumbnail_url: null, // route 가 thumbnail_key 를 조회해 서명 URL 로 채운다(UX ⑦)
  };
}
