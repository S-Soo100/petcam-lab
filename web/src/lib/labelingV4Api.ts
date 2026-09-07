// web/src/lib/labelingV4Api.ts — 브라우저 클라이언트(`/api/labeling-v4/**`).
// request 헬퍼는 labelingV3Api.ts 와 같은 패턴(모듈 private).
'use client';

import { ApiError, UnauthorizedError } from './labelingApi';
import { getSupabaseBrowser } from './supabaseBrowser';
import type { GmeOverlayResponse } from './gmeOverlay';
import type { HighlightDetail, HighlightVerdictInput, HighlightVerdictResult } from './highlightV4';
import type { V4BehaviorFlag, V4CameraOption, V4ClipDetail, V4ClipListResponse, V4ListFilters, V4Member, V4Overview, V4Scope } from './labelingV4';

async function authHeader(): Promise<Record<string, string>> {
  const { data: { session } } = await getSupabaseBrowser().auth.getSession();
  return session ? { Authorization: `Bearer ${session.access_token}` } : {};
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json', ...((init?.headers as Record<string, string>) || {}), ...(await authHeader()) };
  if (init?.body && !headers['Content-Type']) headers['Content-Type'] = 'application/json';
  let resp: Response;
  try { resp = await fetch(path, { ...init, headers }); } catch (e) { throw new ApiError(0, `네트워크 오류: ${(e as Error).message}`); }
  if (resp.status === 401) throw new UnauthorizedError();
  if (!resp.ok) {
    let detail = resp.statusText || `HTTP ${resp.status}`;
    let code: string | undefined;
    try { const j = await resp.json(); if (typeof j?.detail === 'string') detail = j.detail; if (typeof j?.code === 'string') code = j.code; } catch { /* non-JSON */ }
    throw new ApiError(resp.status, detail, undefined, code);
  }
  return resp.json() as Promise<T>;
}

export function v4ListQuery(f: V4ListFilters): string {
  const sp = new URLSearchParams();
  sp.set('scope', f.scope);
  (f.cameraIds ?? []).forEach((id) => sp.append('camera_id', id));
  if (f.labelState) sp.set('label_state', f.labelState);
  if (f.highlightState) sp.set('highlight_state', f.highlightState);
  if (f.behaviorFlag) sp.set('behavior_flag', f.behaviorFlag);
  if (f.cursor) sp.set('cursor', f.cursor);
  if (f.limit != null) sp.set('limit', String(f.limit));
  return sp.toString();
}

export function getV4Clips(f: V4ListFilters): Promise<V4ClipListResponse> {
  return request<V4ClipListResponse>(`/api/labeling-v4/clips?${v4ListQuery(f)}`);
}
export function getV4Clip(clipId: string): Promise<V4ClipDetail> {
  return request<V4ClipDetail>(`/api/labeling-v4/clips/${clipId}`);
}
export function getV4Highlight(clipId: string): Promise<HighlightDetail> {
  return request<HighlightDetail>(`/api/labeling-v4/clips/${clipId}/highlight`);
}
// 같은 카메라의 다음 '라벨 안 된' 영상(서버가 현재 clip 위치를 cursor 로 삼는다). 없으면 null.
export async function getV4NextClip(clipId: string): Promise<string | null> {
  return (await request<{ next_clip_id: string | null }>(`/api/labeling-v4/clips/${clipId}/next`)).next_clip_id;
}
export function submitV4Verdict(clipId: string, input: HighlightVerdictInput & { kind?: 'initial' | 'correction' }): Promise<HighlightVerdictResult> {
  return request<HighlightVerdictResult>(`/api/labeling-v4/clips/${clipId}/verdict`, { method: 'POST', body: JSON.stringify(input) });
}
// "의미있는 행동" 체크/해제. 해제는 체크한 사람·owner 만(403 forbidden).
export function setV4BehaviorFlag(clipId: string, flagged: boolean): Promise<V4BehaviorFlag> {
  return request<V4BehaviorFlag>(`/api/labeling-v4/clips/${clipId}/behavior-flag`, { method: 'POST', body: JSON.stringify({ flagged }) });
}
export function getV4FileUrl(clipId: string): Promise<{ url: string; expires_in: number }> {
  return request(`/api/labeling-v4/clips/${clipId}/file/url`);
}
export function getV4DownloadUrl(clipId: string): Promise<{ url: string; filename: string; expires_in: number }> {
  return request(`/api/labeling-v4/clips/${clipId}/file/url?download=1`);
}
export function getV4GmeOverlay(clipId: string): Promise<GmeOverlayResponse> {
  return request<GmeOverlayResponse>(`/api/labeling-v4/clips/${clipId}/gme-overlay`);
}
export async function getV4Cameras(): Promise<V4CameraOption[]> {
  try { return (await request<{ cameras: V4CameraOption[] }>('/api/labeling-v4/cameras')).cameras; } catch { return []; }
}
export function getV4Members(): Promise<{ members: V4Member[]; cameras: V4CameraOption[] }> {
  return request('/api/labeling-v4/owner/assignments');
}
export function setV4Assignments(userId: string, cameraIds: string[]): Promise<{ camera_ids: string[] }> {
  return request('/api/labeling-v4/owner/assignments', { method: 'PUT', body: JSON.stringify({ user_id: userId, camera_ids: cameraIds }) });
}
// 이어서 라벨링 목적지 — 현재 scope·카메라 필터의 첫 미라벨 영상(남이 보는 중인 건 건너뜀, UX ⑤). 없으면 null.
export async function getV4Continue(scope: V4Scope, cameraIds: string[]): Promise<string | null> {
  const sp = new URLSearchParams();
  sp.set('scope', scope);
  cameraIds.forEach((id) => sp.append('camera_id', id));
  return (await request<{ clip_id: string | null }>(`/api/labeling-v4/continue?${sp.toString()}`)).clip_id;
}
// "이 영상 보는 중" 힌트(UX ⑤). 실패는 무시.
export function claimV4View(clipId: string): Promise<unknown> {
  return request(`/api/labeling-v4/clips/${clipId}/view-claim`, { method: 'POST', body: '{}' }).catch(() => null);
}
// 라벨러 진행(오늘 내가 N개·남은 M개). 전체 clip 집계라 목록 방문 때만 부른다(UX ③).
export function getV4Progress(): Promise<unknown> {
  return request<unknown>('/api/labeling-v4/progress');
}
export function getV4Overview(): Promise<V4Overview> {
  return request<V4Overview>('/api/labeling-v4/owner/overview');
}
