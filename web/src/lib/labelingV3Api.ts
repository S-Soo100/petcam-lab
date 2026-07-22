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
  MotionLabelingState,
  MotionQueueResponse,
} from './labelingV3';

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

export interface MotionClipFileUrl {
  url: string;
  expires_in: number;
}

export async function getMotionClipFileUrl(clipId: string): Promise<MotionClipFileUrl> {
  return request<MotionClipFileUrl>(`/api/labeling-v3/${clipId}/file/url`);
}
