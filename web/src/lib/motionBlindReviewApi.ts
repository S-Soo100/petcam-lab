'use client';

// 그룹 이중 블라인드 라벨링 브라우저 클라이언트 — 전부 same-origin Next.js API route.
//
// ApiError/UnauthorizedError 는 legacy 계약을 재사용해 페이지 오류 처리를 통일한다. lease token 은
// 브라우저가 생성해 per-tab sessionStorage 에만 두고 여기서 요청 body 로만 넘긴다(서버는 응답에
// 되돌려주지 않는다). 상대 판정·digest 는 애초에 응답에 없다(설계 §5.1).

import { ApiError, UnauthorizedError } from './labelingApi';
import { getSupabaseBrowser } from './supabaseBrowser';
import type { GroundTruthInput } from './labelingV2';
import type { BlindDecision, BlindReasonCode } from './motionBlindReview';
import type {
  BlindQueueItem,
  BlindWorkspace,
  BlindClipDetail,
} from './motionBlindReviewServer';
import type {
  BlindHistoryResponse,
  LabelingLibraryItem,
  LabelingLibraryResponse,
  OwnerOverview,
} from './labelingRoleData';

async function authHeader(): Promise<Record<string, string>> {
  const sb = getSupabaseBrowser();
  const {
    data: { session },
  } = await sb.auth.getSession();
  return session ? { Authorization: `Bearer ${session.access_token}` } : {};
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...((init?.headers as Record<string, string>) || {}),
    ...(await authHeader()),
  };
  if (init?.body && !headers['Content-Type']) headers['Content-Type'] = 'application/json';

  let resp: Response;
  try {
    resp = await fetch(path, { ...init, headers });
  } catch (e) {
    throw new ApiError(0, `네트워크 오류: ${(e as Error).message}`);
  }

  if (resp.status === 401) throw new UnauthorizedError();
  if (!resp.ok) {
    let detail = resp.statusText || `HTTP ${resp.status}`;
    let code: string | undefined;
    try {
      const j = await resp.json();
      if (typeof j?.detail === 'string') detail = j.detail;
      if (typeof j?.code === 'string') code = j.code;
    } catch {
      /* 비-JSON 오류 body 는 statusText 로 */
    }
    // API error code(already_submitted / stale_lease / not_assigned / slot_in_use 등)를 보존한다.
    throw new ApiError(resp.status, detail, undefined, code);
  }

  const contentType = resp.headers.get('content-type') || '';
  if (!contentType.includes('application/json')) return undefined as unknown as T;
  return resp.json() as Promise<T>;
}

// ── 읽기 ───────────────────────────────────────────────────────────
export async function getBlindWorkspace(): Promise<BlindWorkspace> {
  const res = await request<{ workspace: BlindWorkspace }>('/api/labeling-v3/blind/workspace');
  return res.workspace;
}

export interface BlindQueueResponse {
  items: BlindQueueItem[];
  next_cursor: string | null;
  has_more: boolean;
}

export async function getBlindQueue(input: {
  activityDay: string;
  cursor?: string | null;
  limit?: number;
}): Promise<BlindQueueResponse> {
  const sp = new URLSearchParams();
  sp.set('activity_day', input.activityDay);
  if (input.cursor) sp.set('cursor', input.cursor);
  if (input.limit != null) sp.set('limit', String(input.limit));
  return request<BlindQueueResponse>(`/api/labeling-v3/blind/queue?${sp.toString()}`);
}

function scopeQuery(cohortId?: string | null): string {
  return cohortId ? `?cohort_id=${encodeURIComponent(cohortId)}` : '';
}

export async function getBlindClip(
  clipId: string,
  cohortId?: string | null,
): Promise<BlindClipDetail> {
  const res = await request<{ clip: BlindClipDetail }>(
    `/api/labeling-v3/blind/${clipId}${scopeQuery(cohortId)}`,
  );
  return res.clip;
}

export interface BlindClipFileUrl {
  url: string;
  expires_in: number;
}

export async function getBlindClipFileUrl(
  clipId: string,
  cohortId?: string | null,
): Promise<BlindClipFileUrl> {
  return request<BlindClipFileUrl>(
    `/api/labeling-v3/blind/${clipId}/file/url${scopeQuery(cohortId)}`,
  );
}

// 동일 canary 링크의 역할별 응답(설계 §8). 라벨러는 자기 작업, Owner 는 집계 현황을 받는다.
export type BlindCanaryResponse =
  | {
      role: 'labeler';
      cohort_id: string;
      items: BlindQueueItem[];
      total_count: number;
      submitted_count: number;
    }
  | {
      role: 'owner';
      cohort_id: string;
      label: string | null;
      status: 'open' | 'closed';
      clip_total: number;
      reviewers: { display_name: string; submitted_count: number; total_count: number }[];
      counts: {
        awaiting: number;
        agreed: number;
        conflict: number;
        owner_resolved: number;
      };
      share_path: string;
    };

export async function getBlindCanary(cohortId: string): Promise<BlindCanaryResponse> {
  return request<BlindCanaryResponse>(`/api/labeling-v3/blind/canary/${cohortId}`);
}

// ── 권한별 읽기 (내 기록 / 영상 보관함 / Owner 현황) ──────────────────
// 필터는 전부 same-origin GET. 응답에는 상대 제출·r2_key·reviewer UUID 가 애초에 없다(설계 §10).
export interface LabelingHistoryFilters {
  decision?: string | null;
  cohortKind?: 'live' | 'canary' | null;
  cameraIds?: string[];
  dateFrom?: string | null; // YYYY-MM-DD (KST 달력일)
  dateTo?: string | null;
  timeFrom?: string | null; // HH:mm (KST, review-fix 5A)
  timeTo?: string | null;
  cursor?: string | null;
  limit?: number;
}

export interface LabelingLibraryFilters {
  labelState?: string | null;
  labelSource?: string | null;
  finalDecision?: string | null; // label|hold|exclude — 서버 필터(review-fix P1-2)
  cameraIds?: string[];
  dateFrom?: string | null;
  dateTo?: string | null;
  timeFrom?: string | null; // HH:mm
  timeTo?: string | null;
  cursor?: string | null;
  limit?: number;
}

function appendCommon(
  sp: URLSearchParams,
  f: { cameraIds?: string[]; dateFrom?: string | null; dateTo?: string | null; cursor?: string | null; limit?: number },
): void {
  (f.cameraIds ?? []).forEach((id) => sp.append('camera_id', id));
  if (f.dateFrom) sp.set('date_from', f.dateFrom);
  if (f.dateTo) sp.set('date_to', f.dateTo);
  if (f.cursor) sp.set('cursor', f.cursor);
  if (f.limit != null) sp.set('limit', String(f.limit));
}

export async function getBlindHistory(
  filters: LabelingHistoryFilters = {},
): Promise<BlindHistoryResponse> {
  const sp = new URLSearchParams();
  appendCommon(sp, filters);
  if (filters.decision) sp.set('decision', filters.decision);
  if (filters.cohortKind) sp.set('cohort_kind', filters.cohortKind);
  if (filters.timeFrom) sp.set('time_from', filters.timeFrom);
  if (filters.timeTo) sp.set('time_to', filters.timeTo);
  const qs = sp.toString();
  return request<BlindHistoryResponse>(`/api/labeling-v3/blind/history${qs ? `?${qs}` : ''}`);
}

export async function getLabelingLibrary(
  filters: LabelingLibraryFilters = {},
): Promise<LabelingLibraryResponse> {
  const sp = new URLSearchParams();
  appendCommon(sp, filters);
  if (filters.labelState) sp.set('label_state', filters.labelState);
  if (filters.labelSource) sp.set('label_source', filters.labelSource);
  if (filters.finalDecision) sp.set('final_decision', filters.finalDecision);
  if (filters.timeFrom) sp.set('time_from', filters.timeFrom);
  if (filters.timeTo) sp.set('time_to', filters.timeTo);
  const qs = sp.toString();
  return request<LabelingLibraryResponse>(`/api/labeling-v3/library${qs ? `?${qs}` : ''}`);
}

export async function getLabelingLibraryClip(clipId: string): Promise<LabelingLibraryItem> {
  return request<LabelingLibraryItem>(`/api/labeling-v3/library/${clipId}`);
}

export async function getLibraryFileUrl(
  clipId: string,
): Promise<{ url: string; expires_in: number }> {
  return request<{ url: string; expires_in: number }>(
    `/api/labeling-v3/library/${clipId}/file/url`,
  );
}

export async function getOwnerOverview(day?: string): Promise<OwnerOverview> {
  const qs = day ? `?activity_day=${encodeURIComponent(day)}` : '';
  return request<OwnerOverview>(`/api/labeling-v3/blind/owner/overview${qs}`);
}

// 역할별 카메라 필터 옵션(설계 §10). 실패해도 필터만 비므로 [] 로 안전 폴백한다.
export async function getMotionCamerasSafe(): Promise<{ id: string; name: string }[]> {
  try {
    const res = await request<{ cameras: { id: string; name: string }[] }>(
      '/api/labeling-v3/cameras',
    );
    return res.cameras;
  } catch {
    return [];
  }
}

// ── lease / 제출 ───────────────────────────────────────────────────
export async function claimBlindReview(input: {
  clipId: string;
  leaseToken: string;
  cohortId?: string | null;
}): Promise<{ lease_expires_at: string | null }> {
  return request<{ lease_expires_at: string | null }>(
    `/api/labeling-v3/blind/${input.clipId}/claim`,
    {
      method: 'POST',
      body: JSON.stringify({
        lease_token: input.leaseToken,
        ...(input.cohortId ? { cohort_id: input.cohortId } : {}),
      }),
    },
  );
}

// 제출 결과는 상대 원문이 없는 두 축뿐이다(설계 §5.1).
export interface BlindSubmitResult {
  status: 'awaiting_peer' | 'agreed' | 'conflict';
  differing_fields?: string[];
}

// ── owner 전용 ─────────────────────────────────────────────────────
export interface ApprovedLabeler {
  user_id: string;
  display_name: string;
}

// 그룹 배정 셀렉터용 승인 라벨러 목록(설계 §2·§6). display_name 우선, 없으면 마스킹 이메일.
// 저장 key 는 user_id(UUID) 뿐 — email 은 화면 표시에만 쓴다.
export async function getApprovedLabelers(): Promise<ApprovedLabeler[]> {
  const res = await request<{ applications: { user_id: string; email?: string | null; display_name?: string | null; status: string }[] }>(
    '/api/labeling-team',
  );
  return res.applications
    .filter((a) => a.status === 'approved')
    .map((a) => ({
      user_id: a.user_id,
      display_name: a.display_name || maskEmail(a.email) || '라벨러',
    }));
}

function maskEmail(email: string | null | undefined): string {
  if (!email) return '';
  const [name, domain] = email.split('@');
  if (!domain) return email.slice(0, 2) + '***';
  return `${name.slice(0, 2)}***@${domain}`;
}

export interface OwnerConflictItem {
  id: string;
  camera_name: string;
  started_at: string;
  differing_fields: string[];
  updated_at: string;
}

export interface OwnerConflictListResponse {
  items: OwnerConflictItem[];
  next_cursor: string | null;
  has_more: boolean;
}

export async function getOwnerConflicts(
  cursor?: string | null,
  cohortId?: string | null,
): Promise<OwnerConflictListResponse> {
  const sp = new URLSearchParams();
  if (cursor) sp.set('cursor', cursor);
  if (cohortId) sp.set('cohort_id', cohortId);
  const qs = sp.toString();
  return request<OwnerConflictListResponse>(
    `/api/labeling-v3/blind/owner/conflicts${qs ? `?${qs}` : ''}`,
  );
}

export interface OwnerSubmissionView {
  decision: string;
  reason_code: string;
  initial_gt: unknown;
  note: string | null;
}

export interface OwnerConflictDetail {
  clip: { id: string; camera_name: string; started_at: string; duration_sec: number; media_ready: boolean } | null;
  status: string;
  differing_fields: string[];
  updated_at: string;
  submission_a: OwnerSubmissionView | null;
  submission_b: OwnerSubmissionView | null;
}

export async function getOwnerConflictDetail(
  clipId: string,
  cohortId?: string | null,
): Promise<OwnerConflictDetail> {
  return request<OwnerConflictDetail>(
    `/api/labeling-v3/blind/owner/${clipId}${scopeQuery(cohortId)}`,
  );
}

export async function getOwnerConflictFileUrl(
  clipId: string,
  cohortId?: string | null,
): Promise<BlindClipFileUrl> {
  return request<BlindClipFileUrl>(
    `/api/labeling-v3/blind/owner/${clipId}/file/url${scopeQuery(cohortId)}`,
  );
}

export async function resolveOwnerConflict(input: {
  clipId: string;
  cohortId?: string | null;
  choice: 'a' | 'b' | 'new';
  finalDecision?: BlindDecision;
  finalGt?: GroundTruthInput | null;
  reason?: string | null;
  expectedUpdatedAt: string;
}): Promise<{ status: string }> {
  return request<{ status: string }>(
    `/api/labeling-v3/blind/owner/${input.clipId}/resolve${scopeQuery(input.cohortId)}`,
    {
      method: 'POST',
      body: JSON.stringify({
        choice: input.choice,
        ...(input.choice === 'new'
          ? {
              final_decision: input.finalDecision,
              final_gt: input.finalGt ?? null,
            }
          : {}),
        reason: input.reason ?? null,
        expected_updated_at: input.expectedUpdatedAt,
      }),
    },
  );
}

export async function manageBlindGroup(input: {
  groupId?: string | null;
  name: string;
  memberIds: string[];
  cameraIds: string[];
}): Promise<{ group_id: string | null }> {
  return request<{ group_id: string | null }>('/api/labeling-v3/blind/owner/groups', {
    method: 'POST',
    body: JSON.stringify({
      ...(input.groupId ? { group_id: input.groupId } : {}),
      name: input.name,
      member_ids: input.memberIds,
      camera_ids: input.cameraIds,
    }),
  });
}

export async function manageBlindCanary(input: {
  action: 'create' | 'close';
  cohortId?: string;
  label?: string | null;
  groupId?: string;
  clipIds?: string[];
  reviewerIds?: string[];
}): Promise<{ cohort_id: string | null }> {
  return request<{ cohort_id: string | null }>('/api/labeling-v3/blind/owner/canary', {
    method: 'POST',
    body: JSON.stringify(
      input.action === 'close'
        ? { action: 'close', cohort_id: input.cohortId }
        : {
            action: 'create',
            group_id: input.groupId,
            clip_ids: input.clipIds,
            reviewer_ids: input.reviewerIds,
            ...(input.label ? { label: input.label } : {}),
          },
    ),
  });
}

export async function submitBlindReview(input: {
  clipId: string;
  decision: BlindDecision;
  initialGt: GroundTruthInput | null;
  note: string | null;
  reasonCode: BlindReasonCode;
  leaseToken: string;
  cohortId?: string | null;
}): Promise<BlindSubmitResult> {
  return request<BlindSubmitResult>(`/api/labeling-v3/blind/${input.clipId}/submit`, {
    method: 'POST',
    body: JSON.stringify({
      decision: input.decision,
      initial_gt: input.initialGt,
      note: input.note,
      reason_code: input.reasonCode,
      lease_token: input.leaseToken,
      ...(input.cohortId ? { cohort_id: input.cohortId } : {}),
    }),
  });
}
