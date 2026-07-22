import 'server-only';

import { NextResponse } from 'next/server';

// motion_clips 운영 라벨링 v3 — server 전용 헬퍼(설계 §7·§9).
//
// 두는 것: RPC/DB row → owner-safe 응답 매핑, prediction snapshot 결정론적 선택,
//          안정 SQLSTATE → 공개 상태코드 매핑, 일반화된 DB 502.
// 절대 통과시키지 않는 것: r2_key/secret/local path/owner_id/evidence/rank_features 등 raw
//          provenance. Postgres 원문 메시지. 매퍼는 지정 필드만 명시적으로 뽑는다(spread 금지).
// 권한 판정은 각 route 가 담당한다(이 모듈은 순수 변환 + 오류 형태만).

import {
  parseMotionState,
  type MotionClipDetail,
  type MotionCompletionReason,
  type MotionLabelingSession,
  type MotionQueueItem,
  type MotionSessionStage,
} from './labelingV3';
import type { GroundTruthInput, VlmErrorTag, VlmVerdict } from './labelingV2';

const PUBLIC_DATABASE_ERROR = '서버 처리 중 오류가 발생했어. 잠시 후 다시 시도해.';

// ── 큐 RPC row → 공개 아이템 ─────────────────────────────────────
// fn_list_motion_clip_labeling_queue 의 반환 row. RPC 는 raw provenance 를 주지 않지만,
// 매퍼는 방어적으로 지정 8필드만 뽑아 어떤 잔여 컬럼도 통과시키지 않는다.
export interface MotionQueueRow {
  clip_id: string;
  camera_id: string;
  camera_name: string | null;
  started_at: string;
  duration_sec: number;
  media_ready: boolean;
  state: string;
  session_stage: string | null;
  state_updated_at: string | null;
}

export function mapMotionQueueRow(row: MotionQueueRow): MotionQueueItem {
  return {
    id: row.clip_id,
    camera_id: row.camera_id,
    camera_name: row.camera_name ?? '',
    started_at: row.started_at,
    duration_sec: Number(row.duration_sec),
    media_ready: Boolean(row.media_ready),
    state: parseMotionState(row.state),
    session_stage: (row.session_stage as MotionSessionStage | null) ?? null,
  };
}

// ── 상세 row → 공개 detail (GT 잠금 전 prediction/evidence 은닉) ───
export interface MotionSessionRow {
  stage: string;
  initial_gt: unknown;
  current_gt: unknown;
  prediction_snapshot: unknown;
  vlm_verdict: string | null;
  vlm_error_tags: string[] | null;
  vlm_review_note: string | null;
  completion_reason: string | null;
  gt_locked_at: string | null;
  completed_at: string | null;
}

export interface MotionDetailRow {
  clip_id: string;
  camera_id: string;
  camera_name: string | null;
  started_at: string;
  duration_sec: number;
  media_ready: boolean;
  state: string;
  state_updated_at?: string | null;
  session: MotionSessionRow | null;
}

function mapSession(row: MotionSessionRow): MotionLabelingSession {
  return {
    stage: row.stage as MotionSessionStage,
    initial_gt: (row.initial_gt as GroundTruthInput | null) ?? null,
    current_gt: (row.current_gt as GroundTruthInput | null) ?? null,
    vlm_verdict: (row.vlm_verdict as VlmVerdict | null) ?? null,
    vlm_error_tags: (row.vlm_error_tags as VlmErrorTag[] | null) ?? [],
    vlm_review_note: row.vlm_review_note ?? null,
    completion_reason: (row.completion_reason as MotionCompletionReason | null) ?? null,
    gt_locked_at: row.gt_locked_at ?? null,
    completed_at: row.completed_at ?? null,
  };
}

export function mapMotionDetailRow(row: MotionDetailRow): MotionClipDetail {
  const detail: MotionClipDetail = {
    id: row.clip_id,
    camera_id: row.camera_id,
    camera_name: row.camera_name ?? '',
    started_at: row.started_at,
    duration_sec: Number(row.duration_sec),
    media_ready: Boolean(row.media_ready),
    state: parseMotionState(row.state),
    state_updated_at: row.state_updated_at ?? null,
    session: null,
  };
  if (row.session) {
    const session = mapSession(row.session);
    detail.session = session;
    // prediction 은 GT 잠금 뒤에만 노출한다(설계 §9). 잠금 전에는 키 자체가 없어야 한다.
    if (session.stage === 'gt_locked' || session.stage === 'completed') {
      detail.prediction =
        (row.session.prediction_snapshot as Record<string, unknown> | null) ?? null;
    }
  }
  return detail;
}

// ── prediction snapshot 선택 (설계 §9) ────────────────────────────
// clip_vlm_jobs row 중 status='succeeded' + object result 만, completed_at DESC → id DESC
// 로 최신을 고른다. failed/retryable/terminal/held 는 prediction 이 아니다. 원본 앨리어싱을
// 막기 위해 deep clone 을 반환한다.
export interface VlmJobRow {
  id: string;
  status: string;
  result: unknown;
  completed_at: string | null;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function selectLatestSucceededPrediction(
  rows: VlmJobRow[],
): Record<string, unknown> | null {
  const succeeded = rows.filter(
    (r) => r.status === 'succeeded' && isPlainObject(r.result),
  );
  if (succeeded.length === 0) return null;
  succeeded.sort((a, b) => {
    const ta = a.completed_at ?? '';
    const tb = b.completed_at ?? '';
    if (ta !== tb) return ta < tb ? 1 : -1; // completed_at DESC
    if (a.id !== b.id) return a.id < b.id ? 1 : -1; // id DESC (tie-break)
    return 0;
  });
  // deep clone — 호출부 row 를 앨리어싱하지 않는 스냅샷.
  return JSON.parse(JSON.stringify(succeeded[0].result)) as Record<string, unknown>;
}

// ── 오류 매핑 ─────────────────────────────────────────────────────
// 안정 SQLSTATE(마이그레이션 §에러 계약) → 공개 상태코드. Postgres 원문은 담지 않는다.
// 미지 코드는 null 을 반환해 호출부가 motionLabelingDatabaseError(502)로 처리하게 한다.
const RPC_ERROR_MAP: Record<string, { status: number; code: string; detail: string }> = {
  '22023': { status: 400, code: 'invalid_request', detail: '요청이 올바르지 않아.' },
  P0002: { status: 404, code: 'not_found', detail: '대상을 찾을 수 없어.' },
  PT403: { status: 404, code: 'not_found', detail: '대상을 찾을 수 없어.' },
  PT409: {
    status: 409,
    code: 'stale_state',
    detail: '다른 화면에서 상태가 바뀌었어. 새로고침 후 다시 시도해.',
  },
  PT410: {
    status: 409,
    code: 'labeling_started',
    detail: '이미 라벨링이 시작된 영상이야.',
  },
  PT422: {
    status: 409,
    code: 'media_unavailable',
    detail: '원본 영상을 재생할 수 없어 라벨링할 수 없어.',
  },
  PT423: { status: 409, code: 'gt_locked', detail: '이미 GT가 잠긴 영상이야.' },
};

export function motionRpcErrorResponse(error: unknown): NextResponse | null {
  const code = (error as { code?: unknown } | null)?.code;
  if (typeof code !== 'string') return null;
  const mapped = RPC_ERROR_MAP[code];
  if (!mapped) return null;
  return NextResponse.json(
    { detail: mapped.detail, code: mapped.code },
    { status: mapped.status },
  );
}

// DB 오류는 서버 로그에만, 응답은 일반화된 502. Supabase 원문/테이블명/트리거 문구 비노출.
export function motionLabelingDatabaseError(error: unknown): NextResponse {
  console.error('[labeling-v3] database error', error);
  return NextResponse.json({ detail: PUBLIC_DATABASE_ERROR }, { status: 502 });
}
