import 'server-only';

// 라벨링 격리함 — server 전용 헬퍼(설계 §8).
//
// 여기 두는 것: cursor 인코딩(Buffer base64url), DB join row → owner-safe 응답 매핑.
// 매퍼는 evidence_snapshot·로컬 경로·producer host 같은 raw provenance 를 절대 통과시키지 않는다.
// owner 인증/권한 판정은 각 route 가 담당한다(이 모듈은 순수 변환만).

import {
  effectiveTriageState,
  triageReasonLabel,
  type TriageCursor,
  type TriageDetail,
  type TriageListItem,
  type TriageOwnerDecision,
  type TriageSuggestedRoute,
  type TriageSuggestionReason,
} from './labelingTriage';

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// ── 상태/필터 (list·detail 라우트 공유) ──────────────────────────
export type TriageListState = 'pending' | 'skipped' | 'labeled';

export interface TriageClipFilters {
  dateFrom?: string;
  dateTo?: string;
  cameraId?: string;
}

// 유효 상태별 현재 row 필터(설계 §5.2).
export function applyTriageStateFilter<
  Q extends { eq: (c: string, v: string) => Q; is: (c: string, v: null) => Q },
>(query: Q, state: TriageListState): Q {
  if (state === 'pending') {
    return query.is('owner_decision', null).eq('suggested_route', 'quarantine');
  }
  if (state === 'skipped') return query.eq('owner_decision', 'skip');
  return query.eq('owner_decision', 'label');
}

// 촬영일·카메라 필터를 camera_clips embed 컬럼에 적용(설계 §8.1). list/count/detail-next 공유.
export function applyTriageClipFilters<
  Q extends {
    eq: (c: string, v: string) => Q;
    gte: (c: string, v: string) => Q;
    lte: (c: string, v: string) => Q;
  },
>(query: Q, f: TriageClipFilters): Q {
  let out = query;
  if (f.cameraId) out = out.eq('camera_clips.camera_id', f.cameraId);
  if (f.dateFrom) out = out.gte('camera_clips.started_at', f.dateFrom);
  if (f.dateTo) out = out.lte('camera_clips.started_at', f.dateTo);
  return out;
}

// query string → 검증된 필터. 잘못된 날짜/카메라는 error 문자열로(라우트가 400 매핑).
export function parseTriageClipFilters(
  search: URLSearchParams,
): { filters: TriageClipFilters } | { error: string } {
  const dateFrom = search.get('date_from') ?? undefined;
  const dateTo = search.get('date_to') ?? undefined;
  const cameraId = search.get('camera_id') ?? undefined;
  if (dateFrom && Number.isNaN(Date.parse(dateFrom))) return { error: '잘못된 date_from' };
  if (dateTo && Number.isNaN(Date.parse(dateTo))) return { error: '잘못된 date_to' };
  if (cameraId && !UUID_RE.test(cameraId)) return { error: '잘못된 camera_id' };
  return { filters: { dateFrom, dateTo, cameraId } };
}

// ── cursor ───────────────────────────────────────────────────────
export function encodeTriageCursor(cursor: TriageCursor): string {
  return Buffer.from(JSON.stringify(cursor)).toString('base64url');
}

// 엄격 디코드 — 손상/위조 커서는 throw 한다(route 가 400 으로 매핑).
export function decodeTriageCursor(raw: string): TriageCursor {
  let parsed: unknown;
  try {
    const json = Buffer.from(raw, 'base64url').toString('utf8');
    parsed = JSON.parse(json);
  } catch {
    throw new Error('invalid cursor encoding');
  }
  if (typeof parsed !== 'object' || parsed === null) {
    throw new Error('invalid cursor payload');
  }
  const { updatedAt, clipId } = parsed as Record<string, unknown>;
  if (typeof updatedAt !== 'string' || Number.isNaN(Date.parse(updatedAt))) {
    throw new Error('invalid cursor updatedAt');
  }
  if (typeof clipId !== 'string' || !UUID_RE.test(clipId)) {
    throw new Error('invalid cursor clipId');
  }
  return { updatedAt, clipId };
}

// ── DB join row → owner-safe 매핑 ────────────────────────────────
// clip_labeling_triage + camera_clips(embed) 조회 결과. evidence_snapshot 은
// 여기 존재할 수 있지만(방어적으로 optional) 매퍼가 응답에 담지 않는다.
export interface TriageJoinRow {
  clip_id: string;
  suggested_route: TriageSuggestedRoute;
  suggestion_reason: TriageSuggestionReason;
  suggestion_source: string;
  policy_version: string;
  owner_decision: TriageOwnerDecision | null;
  decided_at: string | null;
  decision_note: string | null;
  updated_at: string;
  evidence_snapshot?: unknown;
  camera_clips?: EmbeddedClip | EmbeddedClip[] | null;
}

interface EmbeddedClip {
  camera_id?: string | null;
  started_at?: string | null;
  duration_sec?: number | null;
}

// PostgREST 는 to-one embed 를 object 로 주지만 배열로 오는 경우도 방어한다.
function pickClip(embed: TriageJoinRow['camera_clips']): EmbeddedClip {
  if (Array.isArray(embed)) return embed[0] ?? {};
  return embed ?? {};
}

export function mapTriageRowToListItem(row: TriageJoinRow): TriageListItem {
  const clip = pickClip(row.camera_clips);
  return {
    clip_id: row.clip_id,
    camera_id: clip.camera_id ?? null,
    started_at: clip.started_at ?? '',
    duration_sec: clip.duration_sec ?? null,
    suggested_route: row.suggested_route,
    reason: row.suggestion_reason,
    reason_label: triageReasonLabel(row.suggestion_reason),
    owner_decision: row.owner_decision,
    effective_state: effectiveTriageState({
      suggested_route: row.suggested_route,
      owner_decision: row.owner_decision,
    }),
    updated_at: row.updated_at,
  };
}

export function mapTriageRowToDetail(row: TriageJoinRow): TriageDetail {
  return {
    ...mapTriageRowToListItem(row),
    // 최소 provenance 만(설계 §8.2). evidence_snapshot 은 여전히 제외.
    suggestion_source: row.suggestion_source,
    policy_version: row.policy_version,
    decided_at: row.decided_at,
    decision_note: row.decision_note,
  };
}
