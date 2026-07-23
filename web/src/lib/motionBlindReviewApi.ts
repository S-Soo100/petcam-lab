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

export interface BlindCanaryResponse {
  cohort_id: string;
  items: BlindQueueItem[];
  total_count: number;
  submitted_count: number;
}

export async function getBlindCanary(cohortId: string): Promise<BlindCanaryResponse> {
  return request<BlindCanaryResponse>(`/api/labeling-v3/blind/canary/${cohortId}`);
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
