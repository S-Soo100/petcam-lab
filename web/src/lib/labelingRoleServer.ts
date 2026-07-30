import 'server-only';

import { NextResponse } from 'next/server';
import { Buffer } from 'node:buffer';

import {
  collapseFinalStatus,
  type BlindHistoryItem,
  type BlindHistoryResponse,
  type LabelingLibraryItem,
  type LabelingLibraryResponse,
  type OwnerOverview,
  type OwnerOverviewCanary,
  type OwnerOverviewGroup,
  type OwnerOverviewMember,
  type PublicLabelSource,
  type PublicLabelState,
} from './labelingRoleData';

// 권한별 라벨링 읽기 API — server 전용 파서/매퍼(설계 §5·§10).
//
// 두는 것: opaque scope-hash cursor, 요청 필터 검증(DB 접근 전 400), RPC row → allowlist 매핑.
// 절대 통과시키지 않는 것(설계 §10): r2_key·reviewer UUID·상대 제출·digest·lease token·
//   evidence/prediction 원문. 매퍼는 지정 필드만 새 객체로 뽑는다(RPC row spread 금지).

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
// labelingQueueCursor / motionBlindReviewServer 와 동일한 strict RFC3339 — 관대한 파싱 차단.
const RFC3339 = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})$/;
const HHMM = /^(?:[01]\d|2[0-3]):[0-5]\d$/;
const CALENDAR_DAY = /^\d{4}-\d{2}-\d{2}$/;

const DECISIONS = new Set(['label', 'hold', 'exclude']);
const COHORT_KINDS = new Set(['live', 'canary']);
// re_review = canary 재편수 은닉 상태(review-fix P0-1). label_state allowlist 에 포함한다.
const LABEL_STATES = new Set(['final', 'awaiting', 'owner_review', 'unlabeled', 're_review']);
const LABEL_SOURCES = new Set([
  'blind_consensus',
  'owner_single_adopt',
  'owner_legacy',
  'single_legacy',
  'none',
]);

export interface RoleCursor {
  t: string;
  id: string;
}

export type ParseResult<T> =
  | { ok: true; value: T }
  | { ok: false; response: NextResponse };

function badRequest(detail: string): NextResponse {
  return NextResponse.json({ detail, code: 'invalid_request' }, { status: 400 });
}

function validTimestamp(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    value.length <= 64 &&
    RFC3339.test(value) &&
    !Number.isNaN(Date.parse(value))
  );
}

// FNV-1a 32bit — cursor 에 필터 원문을 담지 않기 위한 scope 지문(보안 경계 아님, RPC 가 재검증).
function hashScope(scope: string): string {
  let h = 0x811c9dc5;
  for (let i = 0; i < scope.length; i += 1) {
    h ^= scope.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return (h >>> 0).toString(16);
}

// cursor 는 base64url JSON {v:1,t,id,s}. t 는 PostgreSQL timestamp 텍스트를 그대로 보존한다.
export function encodeRoleCursor(
  position: { t: string; id: string },
  scope: string,
): string {
  return Buffer.from(
    JSON.stringify({ v: 1, t: position.t, id: position.id, s: hashScope(scope) }),
    'utf8',
  ).toString('base64url');
}

export function parseRoleCursor(
  raw: string | null,
  scope: string,
): ParseResult<RoleCursor | null> {
  if (raw === null || raw === '') return { ok: true, value: null };
  try {
    const value = JSON.parse(Buffer.from(raw, 'base64url').toString('utf8')) as Record<
      string,
      unknown
    >;
    if (
      value.v !== 1 ||
      !validTimestamp(value.t) ||
      typeof value.id !== 'string' ||
      !UUID.test(value.id) ||
      value.s !== hashScope(scope)
    ) {
      return { ok: false, response: badRequest('페이지 위치가 올바르지 않아.') };
    }
    return { ok: true, value: { t: value.t as string, id: (value.id as string).toLowerCase() } };
  } catch {
    return { ok: false, response: badRequest('페이지 위치가 올바르지 않아.') };
  }
}

function parseLimit(raw: string | null): number | null {
  if (raw === null) return 30;
  if (!/^\d{1,3}$/.test(raw)) return null;
  const n = Number(raw);
  if (n < 1 || n > 100) return null;
  return n;
}

// 실제 존재하는 달력 날짜인지까지 검증(2026-02-29·2026-13-01 형식만 맞는 값 차단).
function isValidCalendarDay(value: string): boolean {
  if (!CALENDAR_DAY.test(value)) return false;
  const [y, m, d] = value.split('-').map(Number);
  const parsed = new Date(Date.UTC(y, m - 1, d));
  return (
    parsed.getUTCFullYear() === y &&
    parsed.getUTCMonth() === m - 1 &&
    parsed.getUTCDate() === d
  );
}

// KST 달력일 → 그 날의 [00:00, 23:59:59.999] KST 경계(RFC3339, +09:00). 게코 활동은 KST 기준.
function kstDayStart(day: string): string {
  return `${day}T00:00:00+09:00`;
}
function kstDayEnd(day: string): string {
  return `${day}T23:59:59.999+09:00`;
}

// Owner 운영 현황 기본 활동일 = 직전 닫힌 활동일(어제). 활동일 경계 07:00 KST(설계 §3.1).
// nowKST(=UTC+9) 에서 7h 를 뺀 날짜가 현재 활동일, 그 전날이 직전 닫힌 활동일이다.
export function previousClosedActivityDay(now: Date): string {
  const shifted = new Date(now.getTime() + (9 - 7) * 3600_000); // KST wall - 7h
  const currentUtcMidnight = Date.UTC(
    shifted.getUTCFullYear(),
    shifted.getUTCMonth(),
    shifted.getUTCDate(),
  );
  const prev = new Date(currentUtcMidnight - 86400_000);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${prev.getUTCFullYear()}-${pad(prev.getUTCMonth() + 1)}-${pad(prev.getUTCDate())}`;
}

export function parseActivityDay(raw: string | null, now: Date): ParseResult<string> {
  if (raw === null || raw === '') return { ok: true, value: previousClosedActivityDay(now) };
  if (!isValidCalendarDay(raw)) return { ok: false, response: badRequest('활동일이 올바르지 않아.') };
  return { ok: true, value: raw };
}

// camera_id 다중 허용. 각 값은 canonical UUID 여야 하며, 그룹 필터는 붙이지 않는다(모든 카메라).
function parseCameraIds(search: URLSearchParams): string[] | null | 'invalid' {
  const raw = search.getAll('camera_id').filter((v) => v !== '');
  if (raw.length === 0) return null;
  for (const id of raw) {
    if (!UUID.test(id)) return 'invalid';
  }
  return raw.map((id) => id.toLowerCase());
}

// 날짜 범위(YYYY-MM-DD, KST 달력일) → [from 00:00, to 23:59:59.999] KST timestamptz.
function parseDateRange(
  search: URLSearchParams,
): ParseResult<{ from: string | null; to: string | null }> {
  const dateFrom = search.get('date_from');
  const dateTo = search.get('date_to');
  if (dateFrom !== null && !isValidCalendarDay(dateFrom)) {
    return { ok: false, response: badRequest('시작 날짜가 올바르지 않아.') };
  }
  if (dateTo !== null && !isValidCalendarDay(dateTo)) {
    return { ok: false, response: badRequest('끝 날짜가 올바르지 않아.') };
  }
  return {
    ok: true,
    value: {
      from: dateFrom ? kstDayStart(dateFrom) : null,
      to: dateTo ? kstDayEnd(dateTo) : null,
    },
  };
}

// ── 라이브러리 필터 ─────────────────────────────────────────────────
export interface LibraryFilters {
  limit: number;
  cursor: RoleCursor | null;
  scope: string;
  rpc: {
    p_label_state: string | null;
    p_camera_ids: string[] | null;
    p_date_from: string | null;
    p_date_to: string | null;
    p_time_from: string | null;
    p_time_to: string | null;
    p_label_source: string | null;
    p_final_decision: string | null;
    p_cursor_started_at: string | null;
    p_cursor_id: string | null;
  };
}

export function parseLibraryFilters(
  search: URLSearchParams,
): ParseResult<LibraryFilters> {
  const limit = parseLimit(search.get('limit'));
  if (limit === null) return { ok: false, response: badRequest('페이지 크기가 올바르지 않아.') };

  const labelState = search.get('label_state');
  if (labelState !== null && !LABEL_STATES.has(labelState)) {
    return { ok: false, response: badRequest('라벨 상태 필터가 올바르지 않아.') };
  }
  const labelSource = search.get('label_source');
  if (labelSource !== null && !LABEL_SOURCES.has(labelSource)) {
    return { ok: false, response: badRequest('라벨 출처 필터가 올바르지 않아.') };
  }
  // final_decision 은 서버 필터(review-fix P1-2). client-side page 좁힘을 대체하므로 여기서
  // 검증하고 RPC·cursor scope 에 포함한다. allowlist 밖은 400.
  const finalDecision = search.get('final_decision');
  if (finalDecision !== null && !DECISIONS.has(finalDecision)) {
    return { ok: false, response: badRequest('최종 라벨 필터가 올바르지 않아.') };
  }

  const cameras = parseCameraIds(search);
  if (cameras === 'invalid') return { ok: false, response: badRequest('카메라 필터가 올바르지 않아.') };

  const dates = parseDateRange(search);
  if (!dates.ok) return dates;

  const timeFrom = search.get('time_from');
  const timeTo = search.get('time_to');
  // 시간대는 both-or-neither. 자정을 넘는 범위(예 22:00~06:00)는 RPC 가 wrap 처리한다.
  if ((timeFrom === null) !== (timeTo === null)) {
    return { ok: false, response: badRequest('시간대는 시작과 끝을 함께 지정해.') };
  }
  if (timeFrom !== null && (!HHMM.test(timeFrom) || !HHMM.test(timeTo as string))) {
    return { ok: false, response: badRequest('시간대 형식이 올바르지 않아.') };
  }

  const scope = [
    'library',
    labelState ?? '',
    labelSource ?? '',
    finalDecision ?? '',
    (cameras ?? []).join(','),
    dates.value.from ?? '',
    dates.value.to ?? '',
    timeFrom ?? '',
    timeTo ?? '',
  ].join('|');

  const cursorResult = parseRoleCursor(search.get('cursor'), scope);
  if (!cursorResult.ok) return cursorResult;
  const cursor = cursorResult.value;

  return {
    ok: true,
    value: {
      limit,
      cursor,
      scope,
      rpc: {
        p_label_state: labelState,
        p_camera_ids: cameras,
        p_date_from: dates.value.from,
        p_date_to: dates.value.to,
        p_time_from: timeFrom,
        p_time_to: timeTo,
        p_label_source: labelSource,
        p_final_decision: finalDecision,
        p_cursor_started_at: cursor?.t ?? null,
        p_cursor_id: cursor?.id ?? null,
      },
    },
  };
}

// ── 기록 필터 ───────────────────────────────────────────────────────
export interface HistoryFilters {
  limit: number;
  cursor: RoleCursor | null;
  scope: string;
  rpc: {
    p_decision: string | null;
    p_camera_ids: string[] | null;
    p_date_from: string | null;
    p_date_to: string | null;
    p_time_from: string | null;
    p_time_to: string | null;
    p_cohort_kind: string | null;
    p_cursor_submitted_at: string | null;
    p_cursor_id: string | null;
  };
}

export function parseHistoryFilters(
  search: URLSearchParams,
): ParseResult<HistoryFilters> {
  const limit = parseLimit(search.get('limit'));
  if (limit === null) return { ok: false, response: badRequest('페이지 크기가 올바르지 않아.') };

  const decision = search.get('decision');
  if (decision !== null && !DECISIONS.has(decision)) {
    return { ok: false, response: badRequest('판정 필터가 올바르지 않아.') };
  }
  const cohortKind = search.get('cohort_kind');
  if (cohortKind !== null && !COHORT_KINDS.has(cohortKind)) {
    return { ok: false, response: badRequest('코호트 필터가 올바르지 않아.') };
  }

  const cameras = parseCameraIds(search);
  if (cameras === 'invalid') return { ok: false, response: badRequest('카메라 필터가 올바르지 않아.') };

  const dates = parseDateRange(search);
  if (!dates.ok) return dates;

  const timeFrom = search.get('time_from');
  const timeTo = search.get('time_to');
  // 시간대는 both-or-neither(review-fix 5A). 자정 wrap(22:00~06:00)은 RPC 가 처리한다.
  if ((timeFrom === null) !== (timeTo === null)) {
    return { ok: false, response: badRequest('시간대는 시작과 끝을 함께 지정해.') };
  }
  if (timeFrom !== null && (!HHMM.test(timeFrom) || !HHMM.test(timeTo as string))) {
    return { ok: false, response: badRequest('시간대 형식이 올바르지 않아.') };
  }

  const scope = [
    'history',
    decision ?? '',
    cohortKind ?? '',
    (cameras ?? []).join(','),
    dates.value.from ?? '',
    dates.value.to ?? '',
    timeFrom ?? '',
    timeTo ?? '',
  ].join('|');

  const cursorResult = parseRoleCursor(search.get('cursor'), scope);
  if (!cursorResult.ok) return cursorResult;
  const cursor = cursorResult.value;

  return {
    ok: true,
    value: {
      limit,
      cursor,
      scope,
      rpc: {
        p_decision: decision,
        p_camera_ids: cameras,
        p_date_from: dates.value.from,
        p_date_to: dates.value.to,
        p_time_from: timeFrom,
        p_time_to: timeTo,
        p_cohort_kind: cohortKind,
        p_cursor_submitted_at: cursor?.t ?? null,
        p_cursor_id: cursor?.id ?? null,
      },
    },
  };
}

// ── RPC row → 공개 아이템 (allowlist) ──────────────────────────────
export interface LibraryRow {
  clip_id: string;
  camera_id: string | null;
  camera_name: string | null;
  started_at: string;
  duration_sec: number | string;
  label_state: string;
  label_source: string;
  final_decision: string | null;
  final_gt: unknown;
}

export interface HistoryRow {
  submission_id: string;
  clip_id: string;
  camera_id: string | null;
  camera_name: string | null;
  started_at: string;
  duration_sec: number | string;
  media_ready: boolean;
  submitted_at: string;
  decision: string;
  reason_code: string;
  initial_gt: unknown;
  note: string | null;
  cohort_kind: string;
  final_status: string | null;
}

export function mapLibraryRow(row: LibraryRow): LabelingLibraryItem {
  return {
    clip_id: row.clip_id,
    camera_id: row.camera_id ?? null,
    camera_name: row.camera_name ?? null,
    started_at: row.started_at,
    duration_sec: Number(row.duration_sec),
    label_state: row.label_state as PublicLabelState,
    label_source: row.label_source as PublicLabelSource,
    final_decision: row.final_decision ?? null,
    final_gt: row.final_gt ?? null,
  };
}

export function mapHistoryRow(row: HistoryRow): BlindHistoryItem {
  return {
    submission_id: row.submission_id,
    clip_id: row.clip_id,
    camera_id: row.camera_id ?? null,
    camera_name: row.camera_name ?? null,
    started_at: row.started_at,
    duration_sec: Number(row.duration_sec),
    media_ready: Boolean(row.media_ready),
    submitted_at: row.submitted_at,
    decision: row.decision,
    reason_code: row.reason_code,
    initial_gt: row.initial_gt ?? null,
    note: row.note ?? null,
    cohort_kind: row.cohort_kind,
    final_status: collapseFinalStatus(row.final_status),
  };
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : {};
}
function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}
function asString(value: unknown): string {
  return typeof value === 'string' ? value : '';
}
function asCount(value: unknown): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

// Owner overview jsonb → allowlist. reviewer UUID·이메일·개별 제출 body 는 애초에 select 되지
// 않지만, 매퍼도 방어적으로 display_name/count/group·cohort id 만 새 객체로 뽑는다.
export function mapOwnerOverview(value: unknown): OwnerOverview {
  const root = asRecord(value);
  const groups: OwnerOverviewGroup[] = asArray(root.groups).map((g) => {
    const gr = asRecord(g);
    const members: OwnerOverviewMember[] = asArray(gr.members).map((m) => {
      const mr = asRecord(m);
      return {
        display_name: asString(mr.display_name) || '라벨러',
        submitted_count: asCount(mr.submitted_count),
      };
    });
    return {
      group_id: asString(gr.group_id),
      group_name: asString(gr.group_name),
      clip_total: asCount(gr.clip_total),
      members,
      agreed_count: asCount(gr.agreed_count),
      conflict_count: asCount(gr.conflict_count),
      awaiting_count: asCount(gr.awaiting_count),
    };
  });
  const canaries: OwnerOverviewCanary[] = asArray(root.open_canaries).map((c) => {
    const cr = asRecord(c);
    return {
      cohort_id: asString(cr.cohort_id),
      label: cr.label == null ? null : asString(cr.label),
      group_id: cr.group_id == null ? null : asString(cr.group_id),
      clip_total: asCount(cr.clip_total),
      slot_total: asCount(cr.slot_total),
      submitted_total: asCount(cr.submitted_total),
      conflict_count: asCount(cr.conflict_count),
    };
  });
  return {
    activity_day: root.activity_day == null ? null : asString(root.activity_day),
    groups,
    open_canaries: canaries,
  };
}

// ── 페이지 빌더 (keyset) ────────────────────────────────────────────
export function buildLibraryPage(
  rows: LibraryRow[],
  filters: LibraryFilters,
): LabelingLibraryResponse {
  const hasMore = rows.length > filters.limit;
  const page = hasMore ? rows.slice(0, filters.limit) : rows;
  const items = page.map(mapLibraryRow);
  const last = page[page.length - 1];
  const next_cursor =
    hasMore && last
      ? encodeRoleCursor({ t: last.started_at, id: last.clip_id }, filters.scope)
      : null;
  return { items, next_cursor, has_more: hasMore };
}

export function buildHistoryPage(
  rows: HistoryRow[],
  filters: HistoryFilters,
): BlindHistoryResponse {
  const hasMore = rows.length > filters.limit;
  const page = hasMore ? rows.slice(0, filters.limit) : rows;
  const items = page.map(mapHistoryRow);
  const last = page[page.length - 1];
  const next_cursor =
    hasMore && last
      ? encodeRoleCursor({ t: last.submitted_at, id: last.submission_id }, filters.scope)
      : null;
  return { items, next_cursor, has_more: hasMore };
}

export { isValidCalendarDay };
