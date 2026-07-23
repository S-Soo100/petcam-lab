import 'server-only';

import { NextRequest, NextResponse } from 'next/server';
import { Buffer } from 'node:buffer';

import { requireProductionLabelingAccess } from '@/lib/labelingAccess';

// 그룹 이중 블라인드 라벨링 — server 전용 헬퍼(설계 §5·§7).
//
// 두는 것: RPC row → labeler-safe 응답 매핑(allowlist), scope-embedded 큐 cursor,
//          안정 SQLSTATE → 공개 상태코드 매핑, 일반화된 DB 502, labeler 전용 가드.
// 절대 통과시키지 않는 것(설계 §5.1): 상대 제출 decision/GT/note, r2_key, evidence,
//          lease token, digest, 내부 auth UUID, Postgres 원문. 매퍼는 지정 필드만
//          새 객체로 뽑는다(DB row spread 금지).

const PUBLIC_DATABASE_ERROR = '서버 처리 중 오류가 발생했어. 잠시 후 다시 시도해.';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const ACTIVITY_DAY = /^\d{4}-\d{2}-\d{2}$/;
// labelingQueueCursor 와 동일한 strict RFC3339 — filter 문자 누출·모호 instant 방지.
const RFC3339 = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})$/;

// ── 오류 매핑 ─────────────────────────────────────────────────────
// 안정 SQLSTATE(마이그레이션 §에러 계약) → 공개 상태코드. Postgres 원문 비노출.
const RPC_ERROR_MAP: Record<string, { status: number; code: string; detail: string }> = {
  '22023': { status: 400, code: 'invalid_request', detail: '요청이 올바르지 않아.' },
  P0002: { status: 404, code: 'not_found', detail: '대상을 찾을 수 없어.' },
  PT403: { status: 404, code: 'not_assigned', detail: '대상을 찾을 수 없어.' },
  PT409: {
    status: 409,
    code: 'stale_state',
    detail: '다른 화면에서 상태가 바뀌었어. 새로고침 후 다시 시도해.',
  },
  PT410: { status: 409, code: 'already_submitted', detail: '이미 제출한 영상이야.' },
  PT423: {
    status: 409,
    code: 'slot_in_use',
    detail: '다른 창에서 이 영상을 작업 중이야.',
  },
  PT424: {
    status: 410,
    code: 'stale_lease',
    detail: '작업 권한이 만료됐어. 다시 시도해.',
  },
  PT425: {
    status: 409,
    code: 'group_invariant',
    detail: '그룹 구성이 올바르지 않아. 승인된 라벨러 두 명과 카메라를 확인해.',
  },
  PT426: {
    status: 409,
    code: 'not_conflict',
    detail: '불일치 상태가 아닌 영상이라 최종 판정할 수 없어.',
  },
  PT427: {
    status: 410,
    code: 'cohort_closed',
    detail: '검증 링크가 만료됐어.',
  },
};

export function blindRpcErrorResponse(error: unknown): NextResponse | null {
  const code = (error as { code?: unknown } | null)?.code;
  if (typeof code !== 'string') return null;
  const mapped = RPC_ERROR_MAP[code];
  if (!mapped) return null;
  return NextResponse.json({ detail: mapped.detail, code: mapped.code }, { status: mapped.status });
}

export function blindDatabaseError(error: unknown): NextResponse {
  console.error('[blind-review] database error', error);
  return NextResponse.json({ detail: PUBLIC_DATABASE_ERROR }, { status: 502 });
}

export function blindBadRequest(detail: string): NextResponse {
  return NextResponse.json({ detail, code: 'invalid_request' }, { status: 400 });
}

// ── labeler 전용 가드 (설계 §7) ────────────────────────────────────
// owner 는 conflict/admin 라우트만 쓴다(Task 6). 블라인드 labeler 라우트는 승인 labeler 만.
// user id 는 항상 bearer access 에서 온다 — body/query 를 신뢰하지 않는다.
export type BlindLabelerResult =
  | { ok: true; userId: string }
  | { ok: false; response: NextResponse };

export async function requireBlindLabeler(req: NextRequest): Promise<BlindLabelerResult> {
  const access = await requireProductionLabelingAccess(req);
  if (!access.ok) return { ok: false, response: access.response };
  if (access.isOwner) {
    // owner 는 labeler 큐 대상이 아니다(설계 §2·§4.5). 라우트 역할 분리.
    return {
      ok: false,
      response: NextResponse.json({ detail: 'forbidden', code: 'forbidden' }, { status: 403 }),
    };
  }
  return { ok: true, userId: access.userId };
}

// ── scope-embedded 큐 cursor (설계 §4.2·계획 Global Constraints) ────
// version + (started_at,id) + activity day + live/canary scope 를 함께 담아, 다른 날짜나
// live↔canary scope 로 복사된 cursor 를 decode 시점에 400 으로 거부한다.
export interface BlindQueueScope {
  activityDay: string | null;
  cohortKind: 'live' | 'canary';
  cohortId: string | null;
}

export interface BlindQueuePosition {
  startedAt: string;
  id: string;
}

export class InvalidBlindCursorError extends Error {
  constructor() {
    super('invalid_blind_cursor');
    this.name = 'InvalidBlindCursorError';
  }
}

function validTimestamp(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    value.length <= 64 &&
    RFC3339.test(value) &&
    !Number.isNaN(Date.parse(value))
  );
}

export function encodeBlindCursor(scope: BlindQueueScope, position: BlindQueuePosition): string {
  return Buffer.from(
    JSON.stringify({
      v: 1,
      d: scope.activityDay,
      k: scope.cohortKind,
      c: scope.cohortId,
      t: position.startedAt,
      id: position.id,
    }),
    'utf8',
  ).toString('base64url');
}

export function decodeBlindCursor(
  raw: string | null,
  scope: BlindQueueScope,
): BlindQueuePosition | null {
  if (raw === null || raw === '') return null;
  try {
    const value = JSON.parse(Buffer.from(raw, 'base64url').toString('utf8')) as Record<
      string,
      unknown
    >;
    if (
      value.v !== 1 ||
      !validTimestamp(value.t) ||
      typeof value.id !== 'string' ||
      !UUID.test(value.id)
    ) {
      throw new InvalidBlindCursorError();
    }
    // scope 불일치(다른 날짜, live↔canary, 다른 cohort)면 거부(계획 Global Constraints).
    const embeddedDay = value.d === null || value.d === undefined ? null : value.d;
    const embeddedCohort = value.c === null || value.c === undefined ? null : value.c;
    if (
      embeddedDay !== scope.activityDay ||
      value.k !== scope.cohortKind ||
      embeddedCohort !== scope.cohortId
    ) {
      throw new InvalidBlindCursorError();
    }
    return { startedAt: value.t, id: (value.id as string).toLowerCase() };
  } catch (error) {
    if (error instanceof InvalidBlindCursorError) throw error;
    throw new InvalidBlindCursorError();
  }
}

// 요청 파라미터 검증 헬퍼 — 라우트가 DB 접근 전에 400 으로 접는다.
export function isValidUuid(value: string | null): value is string {
  return typeof value === 'string' && UUID.test(value);
}

export function isValidActivityDay(value: string | null): value is string {
  // 자릿수(정규식) → 실제 존재하는 달력 날짜까지 검증(하드닝). 2026-02-29·2026-04-31·2026-13-01
  // 같은 형식만 맞고 존재하지 않는 날짜는 DB 접근 전에 거른다. UTC 성분 round-trip 으로 판정.
  if (typeof value !== 'string' || !ACTIVITY_DAY.test(value)) return false;
  const [year, month, day] = value.split('-').map(Number);
  const parsed = new Date(Date.UTC(year, month - 1, day));
  return (
    parsed.getUTCFullYear() === year &&
    parsed.getUTCMonth() === month - 1 &&
    parsed.getUTCDate() === day
  );
}

// ── 큐 row → 공개 아이템 (allowlist) ──────────────────────────────
// RPC 는 상대 제출·r2_key·evidence 를 주지 않지만, 매퍼는 방어적으로 지정 필드만 새 객체로
// 뽑아 어떤 잔여 컬럼도(설계 §5.1) 통과시키지 않는다.
export interface BlindQueueRow {
  clip_id: string;
  camera_name?: string | null;
  started_at: string;
  duration_sec: number | string;
  media_ready: boolean;
  activity_day_kst: string;
  lease_expires_at?: string | null;
  [extra: string]: unknown;
}

export interface BlindQueueItem {
  id: string;
  camera_name: string;
  started_at: string;
  duration_sec: number;
  media_ready: boolean;
  activity_day: string;
  lease_expires_at: string | null;
}

export function mapBlindQueueRow(row: BlindQueueRow): BlindQueueItem {
  return {
    id: row.clip_id,
    camera_name: row.camera_name ?? '이름 없는 카메라',
    started_at: row.started_at,
    duration_sec: Number(row.duration_sec),
    media_ready: Boolean(row.media_ready),
    activity_day: row.activity_day_kst,
    lease_expires_at: row.lease_expires_at ?? null,
  };
}

// ── workspace row → 공개 집계 (설계 §4.4) ─────────────────────────
// 멤버별 제출 수(집계)만 노출하고, 멤버별 label/hold/exclude 분포는 절대 담지 않는다.
export interface BlindWorkspaceMemberRaw {
  display_name?: string | null;
  submitted_count?: number | string | null;
  [extra: string]: unknown;
}

export interface BlindWorkspaceRow {
  group_id: string | null;
  group_name: string | null;
  priority_activity_day: string | null;
  oldest_unlocked_activity_day: string | null;
  available_days: string[] | null;
  clip_total: number | string;
  own_submitted: number | string;
  partner_submitted: number | string;
  agreed_count: number | string;
  conflict_count: number | string;
  awaiting_count: number | string;
  late_added_count: number | string;
  members: BlindWorkspaceMemberRaw[] | null;
  [extra: string]: unknown;
}

export interface BlindWorkspaceMember {
  display_name: string;
  submitted_count: number;
}

export interface BlindWorkspace {
  group_id: string | null;
  group_name: string | null;
  priority_activity_day: string | null;
  oldest_unlocked_activity_day: string | null;
  available_days: string[];
  clip_total: number;
  own_submitted: number;
  partner_submitted: number;
  agreed_count: number;
  conflict_count: number;
  awaiting_count: number;
  late_added_count: number;
  members: BlindWorkspaceMember[];
}

export function mapBlindWorkspaceRow(row: BlindWorkspaceRow): BlindWorkspace {
  return {
    group_id: row.group_id ?? null,
    group_name: row.group_name ?? null,
    priority_activity_day: row.priority_activity_day ?? null,
    oldest_unlocked_activity_day: row.oldest_unlocked_activity_day ?? null,
    available_days: Array.isArray(row.available_days) ? row.available_days.map(String) : [],
    clip_total: Number(row.clip_total ?? 0),
    own_submitted: Number(row.own_submitted ?? 0),
    partner_submitted: Number(row.partner_submitted ?? 0),
    agreed_count: Number(row.agreed_count ?? 0),
    conflict_count: Number(row.conflict_count ?? 0),
    awaiting_count: Number(row.awaiting_count ?? 0),
    late_added_count: Number(row.late_added_count ?? 0),
    // 멤버는 display_name + submitted_count 만 — 상대 판정 분포는 절대 담지 않는다.
    members: Array.isArray(row.members)
      ? row.members.map((m) => ({
          display_name: String(m.display_name ?? '라벨러'),
          submitted_count: Number(m.submitted_count ?? 0),
        }))
      : [],
  };
}

// ── 상세 row → 공개 detail (상대 제출 0) ──────────────────────────
export interface BlindClipDetailRow {
  clip_id: string;
  camera_name?: string | null;
  started_at: string;
  duration_sec: number | string;
  media_ready: boolean;
  activity_day_kst: string;
  cohort_kind: string;
  own_submitted: boolean;
  [extra: string]: unknown;
}

export interface BlindClipDetail {
  id: string;
  camera_name: string;
  started_at: string;
  duration_sec: number;
  media_ready: boolean;
  activity_day: string;
  cohort_kind: 'live' | 'canary';
  own_submitted: boolean;
}

export function mapBlindClipDetailRow(row: BlindClipDetailRow): BlindClipDetail {
  return {
    id: row.clip_id,
    camera_name: row.camera_name ?? '이름 없는 카메라',
    started_at: row.started_at,
    duration_sec: Number(row.duration_sec),
    media_ready: Boolean(row.media_ready),
    activity_day: row.activity_day_kst,
    cohort_kind: row.cohort_kind === 'canary' ? 'canary' : 'live',
    own_submitted: Boolean(row.own_submitted),
  };
}

// ── owner 전용 매퍼 (설계 §4.5) ────────────────────────────────────
// owner API 만 두 제출을 함께 읽는다. auth UUID·digest·slot·r2_key 는 담지 않고, 판정 비교에
// 필요한 필드만 통과시킨다. labeler 응답에는 절대 쓰지 않는다.
export interface OwnerSubmissionRow {
  decision: string;
  reason_code: string;
  initial_gt: unknown;
  note: string | null;
  [extra: string]: unknown;
}

export interface OwnerSubmission {
  decision: string;
  reason_code: string;
  initial_gt: unknown;
  note: string | null;
}

export function mapOwnerSubmission(row: OwnerSubmissionRow | null): OwnerSubmission | null {
  if (!row) return null;
  return {
    decision: row.decision,
    reason_code: row.reason_code,
    initial_gt: row.initial_gt ?? null,
    note: row.note ?? null,
  };
}

export interface OwnerConflictRow {
  clip_id: string;
  camera_name?: string | null;
  started_at: string;
  differing_fields: string[] | null;
  updated_at: string;
  [extra: string]: unknown;
}

export interface OwnerConflictItem {
  id: string;
  camera_name: string;
  started_at: string;
  differing_fields: string[];
  updated_at: string;
}

export function mapOwnerConflictRow(row: OwnerConflictRow): OwnerConflictItem {
  return {
    id: row.clip_id,
    camera_name: row.camera_name ?? '이름 없는 카메라',
    started_at: row.started_at,
    differing_fields: Array.isArray(row.differing_fields) ? row.differing_fields.map(String) : [],
    updated_at: row.updated_at,
  };
}
