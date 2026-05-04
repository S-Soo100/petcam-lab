'use client';

// 라벨링 웹 → 백엔드 FastAPI fetch 헬퍼.
//
// 모든 호출에 Supabase Auth JWT 를 `Authorization: Bearer` 로 전달.
// 백엔드가 `AUTH_MODE=prod` 일 때 이 토큰을 검증해서 user_id 확정.
// (`AUTH_MODE=dev` 면 백엔드가 토큰 무시하고 DEV_USER_ID 반환 — 로컬 개발 가능.)
//
// 왜 try/catch 한 곳에 모음:
// - 401: 토큰 만료 → 호출부에서 로그인 페이지로 리다이렉트
// - 4xx/5xx: 표준 Error 로 throw → 페이지가 메시지 표시
// - 네트워크 실패: 동일하게 Error
//
// 응답 타입은 백엔드 Pydantic 모델과 1:1.

import { getSupabaseBrowser } from './supabaseBrowser';

const BACKEND_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000';

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = 'ApiError';
  }
}

export class UnauthorizedError extends ApiError {
  constructor(message = 'unauthorized') {
    super(401, message);
    this.name = 'UnauthorizedError';
  }
}

async function authHeader(): Promise<Record<string, string>> {
  const sb = getSupabaseBrowser();
  const {
    data: { session },
  } = await sb.auth.getSession();
  if (!session) return {};
  return { Authorization: `Bearer ${session.access_token}` };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...((init?.headers as Record<string, string>) || {}),
    ...(await authHeader()),
  };
  if (init?.body && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json';
  }

  let resp: Response;
  try {
    resp = await fetch(`${BACKEND_URL}${path}`, { ...init, headers });
  } catch (e) {
    throw new ApiError(0, `네트워크 오류: ${(e as Error).message}`);
  }

  if (resp.status === 401) {
    throw new UnauthorizedError(await safeDetail(resp));
  }
  if (!resp.ok) {
    throw new ApiError(resp.status, await safeDetail(resp));
  }

  // 204 No Content / file 등 비-JSON 처리.
  const contentType = resp.headers.get('content-type') || '';
  if (!contentType.includes('application/json')) {
    return undefined as unknown as T;
  }
  return resp.json() as Promise<T>;
}

async function safeDetail(resp: Response): Promise<string> {
  try {
    const j = await resp.json();
    return typeof j?.detail === 'string' ? j.detail : JSON.stringify(j);
  } catch {
    return resp.statusText || `HTTP ${resp.status}`;
  }
}

// ─────────────────────────────────────────────────────────────────
// 응답 타입 — 백엔드 Pydantic 모델 미러
// ─────────────────────────────────────────────────────────────────

export interface ClipRow {
  id: string;
  user_id: string;
  camera_id: string;
  pet_id: string | null;
  started_at: string;
  ended_at: string;
  duration_sec: number | null;
  has_motion: boolean;
  r2_key: string | null;
  thumbnail_r2_key: string | null;
  // 그 외 필드는 spec §3 에 따라 추가될 수 있음 — extra 무시.
  [key: string]: unknown;
}

export interface QueueResponse {
  items: ClipRow[];
  count: number;
  next_cursor: string | null;
  has_more: boolean;
}

export interface LabelOut {
  id: string;
  clip_id: string;
  labeled_by: string;
  action: string;
  lick_target: string | null;
  note: string | null;
  labeled_at: string;
}

// 4 main + raw 9 — Pydantic Literal 와 일치
export type ActionType =
  | 'eating_paste'
  | 'drinking'
  | 'moving'
  | 'unknown'
  | 'eating_prey'
  | 'defecating'
  | 'shedding'
  | 'basking'
  | 'unseen';

export type LickTargetType =
  | 'air'
  | 'dish'
  | 'floor'
  | 'wall'
  | 'object'
  | 'other';

export interface LabelCreate {
  action: ActionType;
  lick_target?: LickTargetType | null;
  note?: string | null;
  // owner 가 다른 라벨러 라벨을 강제 수정/생성할 때만 명시. 생략 시 본인.
  // 백엔드 검증: labeled_by != self 면 clip owner 인지 확인 → 아니면 403.
  labeled_by?: string | null;
}

// /labels/mine 의 한 row — 라벨 + clip 메타 묶음.
export interface MineItem {
  clip: ClipRow;
  label: LabelOut;
}

export interface MineResponse {
  items: MineItem[];
  count: number;
  next_cursor: string | null;
  has_more: boolean;
}

// behavior_logs 의 VLM 추론 1건 (owner 검수용).
export interface InferenceOut {
  id: string | null;
  clip_id: string;
  action: string;
  source: string;
  confidence: number | null;
  reasoning: string | null;
  vlm_model: string | null;
  created_at: string | null;
}

// ─────────────────────────────────────────────────────────────────
// API 호출
// ─────────────────────────────────────────────────────────────────

export function getQueue(opts?: {
  limit?: number;
  cursor?: string;
}): Promise<QueueResponse> {
  const params = new URLSearchParams();
  if (opts?.limit) params.set('limit', String(opts.limit));
  if (opts?.cursor) params.set('cursor', opts.cursor);
  const qs = params.toString();
  return request<QueueResponse>(`/labels/queue${qs ? `?${qs}` : ''}`);
}

export function getClip(clipId: string): Promise<ClipRow> {
  return request<ClipRow>(`/clips/${encodeURIComponent(clipId)}`);
}

// 백엔드 분기: owner 면 모든 라벨러 row, 라벨러면 본인 row 만 → 호출부 동일.
// 이름은 historical (기존 호출부 prefill 용도). 검수 섹션은 동일 함수로
// 받아서 본인 row 분리해서 표시 (응답 길이 > 1 면 owner 임을 자연스럽게 추론).
export function getMyLabels(clipId: string): Promise<LabelOut[]> {
  return request<LabelOut[]>(
    `/clips/${encodeURIComponent(clipId)}/labels`,
  );
}

// "내 라벨" 회고 목록 — labeled_at desc.
// queue 와 달리 has_motion/r2_key 필터 없음 (회고 흐름은 모든 라벨한 클립 포함).
export function getMyLabeled(opts?: {
  limit?: number;
  cursor?: string;
}): Promise<MineResponse> {
  const params = new URLSearchParams();
  if (opts?.limit) params.set('limit', String(opts.limit));
  if (opts?.cursor) params.set('cursor', opts.cursor);
  const qs = params.toString();
  return request<MineResponse>(`/labels/mine${qs ? `?${qs}` : ''}`);
}

// 클립의 최신 VLM 추론 (owner 전용). 추론 없으면 null.
// 라벨러로 호출하면 백엔드가 403 → ApiError 가 throw 됨.
export function getInference(clipId: string): Promise<InferenceOut | null> {
  return request<InferenceOut | null>(
    `/clips/${encodeURIComponent(clipId)}/inference`,
  );
}

export function createLabel(
  clipId: string,
  body: LabelCreate,
): Promise<LabelOut> {
  return request<LabelOut>(`/clips/${encodeURIComponent(clipId)}/labels`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

// `<video src>` 는 cross-origin 에 Authorization 헤더 못 박음 →
// JSON 엔드포인트로 R2 signed URL 받고 그걸 src 에 박는 표준 패턴.
//
// type: "r2" 면 절대 URL (R2). "local" 이면 백엔드 상대 경로 — local 은
// AUTH_MODE=dev + 같은 origin 에서만 의미 있고 prod 라벨링 웹은 거의 r2 케이스.

export interface PlaybackUrl {
  url: string;
  ttl_sec: number | null;
  type: 'r2' | 'local';
}

export async function getClipFileUrl(clipId: string): Promise<PlaybackUrl> {
  const r = await request<PlaybackUrl>(
    `/clips/${encodeURIComponent(clipId)}/file/url`,
  );
  return resolveLocalUrl(r);
}

export async function getClipThumbnailUrl(
  clipId: string,
): Promise<PlaybackUrl> {
  const r = await request<PlaybackUrl>(
    `/clips/${encodeURIComponent(clipId)}/thumbnail/url`,
  );
  return resolveLocalUrl(r);
}

function resolveLocalUrl(r: PlaybackUrl): PlaybackUrl {
  if (r.type === 'local' && r.url.startsWith('/')) {
    return { ...r, url: `${BACKEND_URL}${r.url}` };
  }
  return r;
}
