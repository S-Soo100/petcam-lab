// web/src/lib/labelingV4Server.ts — 목록 row 매퍼·필터 파서(fail-closed).
import 'server-only';

import { EMPTY_BEHAVIOR_FLAG, EVAL_SAMPLE_ID_RE, FEATURED_DAY_START_HOUR, FEATURED_DAYS, FEATURED_MAX_DAYS, isBehaviorKind, V4_BEHAVIOR_KINDS, type V4BehaviorFlagFilter, type V4BehaviorKind, type V4BehaviorMarks, type V4ClipItem, type V4FeaturedInfo, type V4HighlightState, type V4LabelState, type V4Scope } from './labelingV4';
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
  if (behaviorFlag !== null && behaviorFlag !== 'yes' && !isBehaviorKind(behaviorFlag)) throw new Error('invalid_behavior_flag');
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

// fn_get/set_motion_clip_behavior_flags(4행, kind 별) → Record. 빠진 종류는 미표시. 모르는 kind 는 무시.
export interface BehaviorMarkRow extends BehaviorFlagRow { kind: unknown }
export function mapBehaviorMarks(rows: BehaviorMarkRow[], resolveName: ReviewerNameResolver): V4BehaviorMarks {
  const out = Object.fromEntries(V4_BEHAVIOR_KINDS.map((k) => [k, EMPTY_BEHAVIOR_FLAG])) as V4BehaviorMarks;
  for (const row of rows) {
    if (!isBehaviorKind(row.kind)) continue;
    out[row.kind] = mapBehaviorFlagRow(row, resolveName);
  }
  return out;
}

// 배치 RPC(fn_get_motion_clip_behavior_kinds) 행 → clip_id → kinds. 모르는 kind 는 버린다.
export function mapBehaviorKindsRows(rows: { clip_id: unknown; kinds: unknown }[]): Map<string, V4BehaviorKind[]> {
  const m = new Map<string, V4BehaviorKind[]>();
  for (const r of rows) {
    if (typeof r.clip_id !== 'string' || !Array.isArray(r.kinds)) continue;
    m.set(r.clip_id, r.kinds.filter(isBehaviorKind));
  }
  return m;
}

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
    behavior_kinds: [], // route 가 배치 RPC 로 채운다(보조 정보)
    thumbnail_url: null, // route 가 thumbnail_key 를 조회해 서명 URL 로 채운다(UX ⑦)
    featured: null, // route 가 O 항목에 대해 fn_highlight_featured 로 채운다(보조 정보)
  };
}

// ── ⭐ 대표 tier ─────────────────────────────────────────────────────
export interface V4FeaturedRow {
  clip_id: unknown; camera_id: unknown; camera_name: unknown; started_at: unknown; duration_sec: unknown;
  day_key: unknown; episode_no: unknown; episode_started_at: unknown; episode_ended_at: unknown;
  episode_clip_count: unknown; episode_activity_sec: unknown; episode_rank: unknown; episode_hour_rank: unknown; tier: unknown; is_representative: unknown;
  activity_sec: unknown; highlight_source: unknown; highlight_reason: unknown; reviewer_id: unknown; reviewer_display_name: unknown; behavior_flagged: unknown;
  behavior_kinds?: unknown;
}

export function mapFeaturedInfo(row: V4FeaturedRow, topN: number | null): V4FeaturedInfo {
  if (row.tier !== 'featured' && row.tier !== 'candidate') throw new Error('invalid_featured_row');
  if (typeof row.day_key !== 'string' || typeof row.episode_rank !== 'number' || typeof row.episode_clip_count !== 'number') throw new Error('invalid_featured_row');
  return {
    tier: row.tier,
    day_key: row.day_key,
    episode_rank: row.episode_rank,
    episode_hour_rank: typeof row.episode_hour_rank === 'number' ? row.episode_hour_rank : row.episode_rank,
    episode_clip_count: row.episode_clip_count,
    episode_activity_sec: Number(row.episode_activity_sec ?? 0), // PostgREST numeric 은 숫자로 오지만 방어
    is_representative: row.is_representative === true,
    top_n: topN,
  };
}

// feed 행 → 목록 카드 항목(`⭐ 대표만` 화면). reviewer UUID 는 표시명으로만. 썸네일은 route 가 붙인다.
export function mapFeaturedRowToItem(row: V4FeaturedRow, topN: number | null, resolveName: ReviewerNameResolver): V4ClipItem {
  if (typeof row.clip_id !== 'string' || typeof row.started_at !== 'string' || typeof row.camera_name !== 'string') throw new Error('invalid_featured_row');
  if (row.highlight_source !== 'human' && row.highlight_source !== 'rule') throw new Error('invalid_featured_row');
  if (row.highlight_source === 'human' && (typeof row.reviewer_id !== 'string' || !UUID_RE.test(row.reviewer_id))) throw new Error('invalid_featured_row');
  return {
    id: row.clip_id,
    camera_id: typeof row.camera_id === 'string' ? row.camera_id : null,
    camera_name: row.camera_name,
    started_at: row.started_at,
    duration_sec: typeof row.duration_sec === 'number' ? row.duration_sec : row.duration_sec === null ? null : Number(row.duration_sec),
    media_ready: true, // 함수가 media_deleted 를 이미 걸렀다
    highlight: {
      source: row.highlight_source,
      status: 'decided',
      value: true,
      reason: typeof row.highlight_reason === 'string' ? row.highlight_reason : '',
      reviewer_name: row.highlight_source === 'human'
        ? resolveName(row.reviewer_id as string, typeof row.reviewer_display_name === 'string' ? row.reviewer_display_name : null)
        : null,
      decided_at: null,
    },
    behavior_flag: { flagged: row.behavior_flagged === true, flagged_by_name: null, flagged_at: null },
    behavior_kinds: Array.isArray(row.behavior_kinds) ? row.behavior_kinds.filter(isBehaviorKind) : [],
    thumbnail_url: null,
    featured: mapFeaturedInfo(row, topN),
  };
}

// 하루 키(20:00 경계). 서울은 DST 가 없어 고정 +9h — 서버 `AT TIME ZONE 'Asia/Seoul'` 와 같은 답.
const SEOUL_OFFSET_MS = 9 * 3_600_000;
const DAY_MS = 86_400_000;
export function dayKeyOf(iso: string, dayStartHour = FEATURED_DAY_START_HOUR): string {
  return new Date(Date.parse(iso) + SEOUL_OFFSET_MS - dayStartHour * 3_600_000).toISOString().slice(0, 10);
}
export function dayKeyStartUtc(dayKey: string, dayStartHour = FEATURED_DAY_START_HOUR): Date {
  const [y, m, d] = dayKey.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d, dayStartHour) - SEOUL_OFFSET_MS);
}
// 항목들의 하루 키를 모두 덮는 [from, to). 목록 페이지에 tier 를 붙일 때.
export function featuredWindowFor(startedAts: string[]): { from: string; to: string } | null {
  if (startedAts.length === 0) return null;
  const keys = startedAts.map((s) => dayKeyOf(s)).sort();
  const from = dayKeyStartUtc(keys[0]);
  const to = new Date(dayKeyStartUtc(keys[keys.length - 1]).getTime() + DAY_MS);
  return { from: from.toISOString(), to: to.toISOString() };
}
// 오늘 키 기준 최근 N일(petcam-api featured_window 와 같은 정의 — `now - N일` 로 자르면 첫 하루가 반쪽).
export function featuredWindowDays(now: Date, days: number): { from: string; to: string } {
  const from = new Date(dayKeyStartUtc(dayKeyOf(now.toISOString())).getTime() - (days - 1) * DAY_MS);
  return { from: from.toISOString(), to: now.toISOString() };
}

export interface V4FeaturedRequest { days: number; cameraIds: string[] | null }
export function parseV4FeaturedRequest(sp: URLSearchParams): V4FeaturedRequest {
  const cameraIds = sp.getAll('camera_id');
  for (const id of cameraIds) if (!UUID_RE.test(id)) throw new Error('invalid_camera_id');
  const rawDays = sp.get('days');
  const days = rawDays === null ? FEATURED_DAYS : Number(rawDays);
  if (!Number.isInteger(days) || days < 1 || days > FEATURED_MAX_DAYS) throw new Error('invalid_days');
  return { days, cameraIds: cameraIds.length ? cameraIds : null };
}
