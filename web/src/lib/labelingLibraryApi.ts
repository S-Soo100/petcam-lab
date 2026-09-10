// web/src/lib/labelingLibraryApi.ts — 공용 영상 보관함 브라우저 클라이언트.
// 이중 blind 클라이언트 모듈(퇴역, 2026-09-08)에서 보관함 함수만 옮겼다(동작 동일).
'use client';

import { ApiError, UnauthorizedError } from './labelingApi';
import { getSupabaseBrowser } from './supabaseBrowser';
import type { LabelingLibraryItem, LabelingLibraryResponse } from './labelingRoleData';

async function authHeader(): Promise<Record<string, string>> {
  const {
    data: { session },
  } = await getSupabaseBrowser().auth.getSession();
  return session ? { Authorization: `Bearer ${session.access_token}` } : {};
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...((init?.headers as Record<string, string>) || {}),
    ...(await authHeader()),
  };
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
  return resp.json() as Promise<T>;
}

export interface LabelingLibraryFilters {
  labelState?: string | null;
  labelSource?: string | null;
  finalDecision?: string | null; // label|hold|exclude — 서버 필터(review-fix P1-2)
  cameraIds?: string[];
  dateFrom?: string | null; // YYYY-MM-DD (KST 달력일)
  dateTo?: string | null;
  timeFrom?: string | null; // HH:mm
  timeTo?: string | null;
  cursor?: string | null;
  limit?: number;
}

export async function getLabelingLibrary(filters: LabelingLibraryFilters = {}): Promise<LabelingLibraryResponse> {
  const sp = new URLSearchParams();
  (filters.cameraIds ?? []).forEach((id) => sp.append('camera_id', id));
  if (filters.dateFrom) sp.set('date_from', filters.dateFrom);
  if (filters.dateTo) sp.set('date_to', filters.dateTo);
  if (filters.cursor) sp.set('cursor', filters.cursor);
  if (filters.limit != null) sp.set('limit', String(filters.limit));
  if (filters.labelState) sp.set('label_state', filters.labelState);
  if (filters.labelSource) sp.set('label_source', filters.labelSource);
  if (filters.finalDecision) sp.set('final_decision', filters.finalDecision);
  if (filters.timeFrom) sp.set('time_from', filters.timeFrom);
  if (filters.timeTo) sp.set('time_to', filters.timeTo);
  const qs = sp.toString();
  return request<LabelingLibraryResponse>(`/api/labeling-v3/library${qs ? `?${qs}` : ''}`);
}

export function getLabelingLibraryClip(clipId: string): Promise<LabelingLibraryItem> {
  return request<LabelingLibraryItem>(`/api/labeling-v3/library/${clipId}`);
}

export function getLibraryFileUrl(clipId: string): Promise<{ url: string; expires_in: number }> {
  return request(`/api/labeling-v3/library/${clipId}/file/url`);
}

export function getLibraryDownloadUrl(clipId: string): Promise<{ url: string; filename: string; expires_in: number }> {
  return request(`/api/labeling-v3/library/${clipId}/file/url?download=1`);
}

// 역할별 카메라 필터 옵션(설계 §10). 실패해도 필터만 비므로 [] 로 안전 폴백한다.
export async function getMotionCamerasSafe(): Promise<{ id: string; name: string }[]> {
  try {
    return (await request<{ cameras: { id: string; name: string }[] }>('/api/labeling-v3/cameras')).cameras;
  } catch {
    return [];
  }
}
