'use client';

// motion_clips 운영 라벨링 v3 브라우저 클라이언트 — 큰 legacy labelingApi.ts 와 분리한다.
//
// v3 는 전부 same-origin Next.js API route(/api/labeling-v3/**)라 BACKEND_URL 분기가 없다.
// ApiError/UnauthorizedError 는 legacy 와 동일 계약을 재사용해 페이지 오류 처리를 통일한다.

import { ApiError, UnauthorizedError } from './labelingApi';
import { getSupabaseBrowser } from './supabaseBrowser';
import type {
  MotionCameraOption,
  MotionClipDetail,
  MotionCompletionReason,
  MotionLabelingState,
  MotionNextResponse,
  MotionQueueResponse,
  MotionSessionStage,
} from './labelingV3';
import type { MotionQueueUiFilters } from './labelingV3QueueClient';
import type { GroundTruthInput, VlmErrorTag, VlmVerdict } from './labelingV2';

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
    throw new ApiError(resp.status, detail, undefined, code);
  }

  const contentType = resp.headers.get('content-type') || '';
  if (!contentType.includes('application/json')) return undefined as unknown as T;
  return resp.json() as Promise<T>;
}

export interface MotionQueueFilters {
  limit?: number;
  cursor?: string | null;
  state?: MotionLabelingState | 'all';
  cameraIds?: string[];
  dateFrom?: string;
  dateTo?: string;
  media?: 'ready' | 'unavailable';
}

function queueSearchParams(filters: MotionQueueFilters): URLSearchParams {
  const sp = new URLSearchParams();
  if (filters.limit != null) sp.set('limit', String(filters.limit));
  if (filters.cursor) sp.set('cursor', filters.cursor);
  if (filters.state && filters.state !== 'all') sp.set('state', filters.state);
  if (filters.cameraIds && filters.cameraIds.length) {
    sp.set('camera_id', filters.cameraIds.join(','));
  }
  if (filters.dateFrom) sp.set('date_from', filters.dateFrom);
  if (filters.dateTo) sp.set('date_to', filters.dateTo);
  if (filters.media) sp.set('media', filters.media);
  return sp;
}

export async function getMotionQueue(
  filters: MotionQueueFilters = {},
): Promise<MotionQueueResponse> {
  const qs = queueSearchParams(filters).toString();
  return request<MotionQueueResponse>(`/api/labeling-v3/queue${qs ? `?${qs}` : ''}`);
}

export async function getMotionCameras(): Promise<MotionCameraOption[]> {
  const res = await request<{ cameras: MotionCameraOption[] }>('/api/labeling-v3/cameras');
  return res.cameras;
}

export async function getMotionClip(clipId: string): Promise<MotionClipDetail> {
  return request<MotionClipDetail>(`/api/labeling-v3/${clipId}`);
}

// owner 전용: 현재 필터의 다음 미분류 영상. state 는 서버가 unreviewed 로 강제하므로 보내지 않고,
// camera/date/media 문맥만 전달한다(설계 §6). next 가 없으면 { next_clip_id: null }.
export async function getNextUnreviewedMotionClip(
  clipId: string,
  filters: MotionQueueUiFilters,
): Promise<MotionNextResponse> {
  const sp = new URLSearchParams();
  if (filters.camera_id?.length) sp.set('camera_id', filters.camera_id.join(','));
  if (filters.date_from) sp.set('date_from', filters.date_from);
  if (filters.date_to) sp.set('date_to', filters.date_to);
  if (filters.media) sp.set('media', filters.media);
  const qs = sp.toString();
  return request<MotionNextResponse>(`/api/labeling-v3/${clipId}/next${qs ? `?${qs}` : ''}`);
}

export interface MotionClipFileUrl {
  url: string;
  expires_in: number;
}

export async function getMotionClipFileUrl(clipId: string): Promise<MotionClipFileUrl> {
  return request<MotionClipFileUrl>(`/api/labeling-v3/${clipId}/file/url`);
}

export type MotionDecision = 'label' | 'hold' | 'skip' | 'reset';

export interface MotionDecisionResult {
  clip_id: string;
  state: MotionLabelingState;
  decided_at: string | null;
  note: string | null;
  updated_at: string;
}

export async function decideMotionClip(
  clipId: string,
  input: { decision: MotionDecision; expected_updated_at?: string | null; note?: string | null },
): Promise<MotionDecisionResult> {
  return request<MotionDecisionResult>(`/api/labeling-v3/${clipId}/decision`, {
    method: 'POST',
    body: JSON.stringify({
      decision: input.decision,
      expected_updated_at: input.expected_updated_at ?? null,
      note: input.note ?? null,
    }),
  });
}

export interface MotionGtLockResult {
  stage: MotionSessionStage;
  prediction: Record<string, unknown> | null;
  requires_vlm_review: boolean;
}

// blind GT 잠금. prediction/reviewer/stage 는 서버가 정하므로 GT 만 넘긴다.
export async function lockMotionGt(
  clipId: string,
  gt: GroundTruthInput,
): Promise<MotionGtLockResult> {
  return request<MotionGtLockResult>(`/api/labeling-v3/${clipId}/gt`, {
    method: 'POST',
    body: JSON.stringify(gt),
  });
}

export interface MotionVlmReviewResult {
  stage: MotionSessionStage;
  completion_reason: MotionCompletionReason | null;
}

// prediction 있으면 verdict 필수, 없으면 verdict 생략(no_prediction 완료).
export async function completeMotionVlmReview(
  clipId: string,
  input?: { verdict?: VlmVerdict; error_tags?: VlmErrorTag[]; note?: string | null },
): Promise<MotionVlmReviewResult> {
  const body =
    input?.verdict != null
      ? { verdict: input.verdict, error_tags: input.error_tags ?? [], note: input.note ?? null }
      : { note: input?.note ?? null };
  return request<MotionVlmReviewResult>(`/api/labeling-v3/${clipId}/vlm-review`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export async function reviseMotionGt(
  clipId: string,
  input: { gt: GroundTruthInput; reason: string },
): Promise<{ ok: boolean; stage: MotionSessionStage }> {
  return request<{ ok: boolean; stage: MotionSessionStage }>(`/api/labeling-v3/${clipId}/revise`, {
    method: 'POST',
    body: JSON.stringify({ gt: input.gt, reason: input.reason }),
  });
}
