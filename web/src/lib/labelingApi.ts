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
import type {
  GroundTruthInput,
  LabelingSession,
  VlmReviewInput,
} from './labelingV2';
import type {
  FeedbackContent,
  TutorialAccess,
  TutorialAttemptStage,
  TutorialComparison,
} from './labelingTutorial';

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

  // path 가 `/api/` 로 시작하면 같은 origin (Next.js API route, Vercel 호스팅).
  // 아니면 외부 FastAPI 백엔드 (BACKEND_URL). 일부 endpoint 는 Next.js 로
  // 이식돼서 백엔드 맥북 의존이 끊김 (영상 URL/라벨/추론/클립 메타).
  const url = path.startsWith('/api/') ? path : `${BACKEND_URL}${path}`;

  let resp: Response;
  try {
    resp = await fetch(url, { ...init, headers });
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
  ended_at?: string;
  duration_sec: number | null;
  has_motion: boolean;
  r2_key: string | null;
  thumbnail_r2_key: string | null;
  // 큐 응답(GET /labels/queue)에서만 백엔드가 채우는 파생 필드 — 단건 clip 조회엔 없음.
  // 썸네일은 GET /clips/{id}/thumbnail/url 로 일원화(R1) → 큐 응답 thumb_url 폐기.
  vlm_action?: string | null; // behavior_logs source=vlm 최신 자동 판정 (없으면 미분석)
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

// 4 main + raw + OOD — 백엔드 labels.py ActionType Literal 와 일치 유지
export type ActionType =
  | 'eating_paste'
  | 'drinking'
  | 'moving'
  | 'unknown'
  | 'eating_prey'
  | 'defecating'
  | 'shedding'
  | 'basking'
  | 'unseen'
  | 'hand_feeding';

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

export interface LabelingV2State {
  clip: ClipRow;
  session: LabelingSession | null;
  system_metadata: Record<string, unknown>;
}

export interface GroundTruthSaveResult {
  session: LabelingSession;
  prediction: Record<string, unknown> | null;
  requires_vlm_review: boolean;
}

// 라벨링 접근 상태 (GET /api/labeling-access) — 서버 getLabelingAccess 미러.
export type LabelingAccessStatus =
  | 'owner'
  | 'labeler'
  | 'pending'
  | 'rejected'
  | 'unregistered';

export interface LabelingAccessInfo {
  status: LabelingAccessStatus;
  display_name: string | null;
  email: string;
  // 교육 완료 축(설계 §11). 멤버십(status)과 별도. 구버전 서버 호환 위해 optional.
  tutorial?: TutorialAccess;
}

// 라벨러 참여 신청 결과 row (POST /api/labeler-applications).
export interface LabelerApplication {
  user_id: string;
  email: string;
  display_name: string;
  status: 'pending' | 'approved' | 'rejected';
  requested_at: string;
  reviewed_at: string | null;
}

// ─────────────────────────────────────────────────────────────────
// API 호출
// ─────────────────────────────────────────────────────────────────

// 로그인 후 어디로 보낼지 결정하는 접근 상태 조회. 401 이면 세션 만료.
export function getLabelingAccess(): Promise<LabelingAccessInfo> {
  return request<LabelingAccessInfo>('/api/labeling-access');
}

// 라벨러 참여 신청. 이미 라벨러/거절 상태면 409.
export function applyForLabeling(displayName: string): Promise<LabelerApplication> {
  return request<LabelerApplication>('/api/labeler-applications', {
    method: 'POST',
    body: JSON.stringify({ display_name: displayName }),
  });
}

// ── 팀원 관리 (owner) ─────────────────────────────────────────────
export type TeamDecision = 'approve' | 'reject' | 'deactivate';

export function getLabelingTeam(): Promise<{ applications: LabelerApplication[] }> {
  return request<{ applications: LabelerApplication[] }>('/api/labeling-team');
}

export function decideLabelingTeam(
  userId: string,
  decision: TeamDecision,
): Promise<{ application: LabelerApplication }> {
  return request<{ application: LabelerApplication }>(
    `/api/labeling-team/${encodeURIComponent(userId)}/decision`,
    { method: 'POST', body: JSON.stringify({ decision }) },
  );
}

// ── 필터 (백엔드 R3/R4 계약) ──────────────────────────────────────
export interface CameraOption {
  id: string;
  name: string;
}
export interface FilterOptions {
  cameras: CameraOption[];
}

// 필터 드롭다운 옵션 (카메라 목록, 스코프 반영). 백엔드 R4.
export function getFilterOptions(): Promise<FilterOptions> {
  return request<FilterOptions>('/labels/filter-options');
}

// 큐 필터 축. 다중값은 comma-join 으로 전달 (백엔드가 split).
export interface QueueFilters {
  camera_id?: string[];
  vlm_action?: string[];
  has_vlm?: boolean;
  date_from?: string;
  date_to?: string;
}
// 내라벨 필터 축.
export interface MineFilters {
  action?: string[];
  lick_target?: string[];
  camera_id?: string[];
  date_from?: string;
  date_to?: string;
}

function appendCsv(p: URLSearchParams, key: string, vals?: string[]) {
  if (vals && vals.length) p.set(key, vals.join(','));
}

export function getQueue(opts?: {
  limit?: number;
  cursor?: string;
  filters?: QueueFilters;
}): Promise<QueueResponse> {
  const params = new URLSearchParams();
  if (opts?.limit) params.set('limit', String(opts.limit));
  if (opts?.cursor) params.set('cursor', opts.cursor);
  const f = opts?.filters;
  if (f) {
    appendCsv(params, 'camera_id', f.camera_id);
    appendCsv(params, 'vlm_action', f.vlm_action);
    if (f.has_vlm !== undefined) params.set('has_vlm', String(f.has_vlm));
    if (f.date_from) params.set('date_from', f.date_from);
    if (f.date_to) params.set('date_to', f.date_to);
  }
  const qs = params.toString();
  return request<QueueResponse>(`/api/labeling-v2/queue${qs ? `?${qs}` : ''}`);
}

export function getClip(clipId: string): Promise<ClipRow> {
  return request<ClipRow>(`/api/clips/${encodeURIComponent(clipId)}`);
}

// 백엔드 분기: owner 면 모든 라벨러 row, 라벨러면 본인 row 만 → 호출부 동일.
// 이름은 historical (기존 호출부 prefill 용도). 검수 섹션은 동일 함수로
// 받아서 본인 row 분리해서 표시 (응답 길이 > 1 면 owner 임을 자연스럽게 추론).
export function getMyLabels(clipId: string): Promise<LabelOut[]> {
  return request<LabelOut[]>(
    `/api/clips/${encodeURIComponent(clipId)}/labels`,
  );
}

// "내 라벨" 회고 목록 — labeled_at desc.
// queue 와 달리 has_motion/r2_key 필터 없음 (회고 흐름은 모든 라벨한 클립 포함).
export function getMyLabeled(opts?: {
  limit?: number;
  cursor?: string;
  filters?: MineFilters;
}): Promise<MineResponse> {
  const params = new URLSearchParams();
  if (opts?.limit) params.set('limit', String(opts.limit));
  if (opts?.cursor) params.set('cursor', opts.cursor);
  const f = opts?.filters;
  if (f) {
    appendCsv(params, 'action', f.action);
    appendCsv(params, 'lick_target', f.lick_target);
    appendCsv(params, 'camera_id', f.camera_id);
    if (f.date_from) params.set('date_from', f.date_from);
    if (f.date_to) params.set('date_to', f.date_to);
  }
  const qs = params.toString();
  return request<MineResponse>(`/labels/mine${qs ? `?${qs}` : ''}`);
}

// 클립의 최신 VLM 추론 (owner 전용). 추론 없으면 null.
// 라벨러로 호출하면 백엔드가 403 → ApiError 가 throw 됨.
export function getInference(clipId: string): Promise<InferenceOut | null> {
  return request<InferenceOut | null>(
    `/api/clips/${encodeURIComponent(clipId)}/inference`,
  );
}

export function getLabelingV2(clipId: string): Promise<LabelingV2State> {
  return request<LabelingV2State>(
    `/api/labeling-v2/${encodeURIComponent(clipId)}`,
  );
}

export function saveGroundTruth(
  clipId: string,
  body: GroundTruthInput,
): Promise<GroundTruthSaveResult> {
  return request<GroundTruthSaveResult>(
    `/api/labeling-v2/${encodeURIComponent(clipId)}/gt`,
    { method: 'POST', body: JSON.stringify(body) },
  );
}

export function saveVlmReview(
  clipId: string,
  body: VlmReviewInput,
): Promise<{ session: LabelingSession }> {
  return request<{ session: LabelingSession }>(
    `/api/labeling-v2/${encodeURIComponent(clipId)}/vlm-review`,
    { method: 'POST', body: JSON.stringify(body) },
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

export interface DownloadUrl extends PlaybackUrl {
  filename: string;
}

export type RouterReviewVisibleGecko = 'yes' | 'no' | 'unclear';
export type RouterReviewActionGt =
  | 'moving'
  | 'static'
  | 'feeding'
  | 'drinking'
  | 'hidden'
  | 'unseen'
  | 'human_noise'
  | 'other';
export type RouterReviewOk = 'yes' | 'no' | 'unclear';

export interface RouterReviewLabel {
  id: string;
  review_item_id: string;
  clip_id: string;
  reviewed_by: string;
  manual_visible_gecko: RouterReviewVisibleGecko;
  manual_action_gt: RouterReviewActionGt;
  manual_router_ok: RouterReviewOk;
  manual_notes: string | null;
  reviewed_at: string;
}

export interface RouterReviewItem {
  id: string;
  batch_id: string;
  clip_id: string;
  sample_group: string;
  route: 'cloud_now' | 'cloud_later' | 'activity_only' | 'review_candidate';
  risk: 'low' | 'medium' | 'high';
  reason: string;
  priority: number;
  camera_id: string | null;
  started_at: string | null;
  evidence_reliability: 'low' | 'medium' | 'high' | null;
  motion_mean: number | null;
  motion_peak: number | null;
  active_motion_ratio: number | null;
  motion_burst_count: number | null;
  label: RouterReviewLabel | null;
}

export interface RouterReviewBatch {
  batch_id: string;
  count: number;
  reviewed_count: number;
}

export interface RouterReviewItemsResponse {
  items: RouterReviewItem[];
  count: number;
  reviewed_count: number;
}

export interface RouterReviewItemResponse {
  item: RouterReviewItem;
  clip: ClipRow;
  next_clip_id: string | null;
  next_unreviewed_clip_id: string | null;
}

export interface RouterReviewLabelCreate {
  manual_visible_gecko: RouterReviewVisibleGecko;
  manual_action_gt: RouterReviewActionGt;
  manual_router_ok: RouterReviewOk;
  manual_notes?: string | null;
}

export async function getClipFileUrl(clipId: string): Promise<PlaybackUrl> {
  const r = await request<PlaybackUrl>(
    `/api/clips/${encodeURIComponent(clipId)}/file/url`,
  );
  return resolveLocalUrl(r);
}

export function getClipDownloadUrl(clipId: string): Promise<DownloadUrl> {
  return request<DownloadUrl>(
    `/api/clips/${encodeURIComponent(clipId)}/download/url`,
  );
}

export async function getClipThumbnailUrl(
  clipId: string,
): Promise<PlaybackUrl> {
  const r = await request<PlaybackUrl>(
    `/api/clips/${encodeURIComponent(clipId)}/thumbnail/url`,
  );
  return resolveLocalUrl(r);
}

export function getRouterReviewBatches(): Promise<RouterReviewBatch[]> {
  return request<RouterReviewBatch[]>('/api/router-review/batches');
}

export function getRouterReviewItems(opts?: {
  batch_id?: string;
  sample_group?: string;
  status?: 'all' | 'reviewed' | 'unreviewed';
}): Promise<RouterReviewItemsResponse> {
  const params = new URLSearchParams();
  if (opts?.batch_id) params.set('batch_id', opts.batch_id);
  if (opts?.sample_group) params.set('sample_group', opts.sample_group);
  if (opts?.status) params.set('status', opts.status);
  const qs = params.toString();
  return request<RouterReviewItemsResponse>(
    `/api/router-review/items${qs ? `?${qs}` : ''}`,
  );
}

export function getRouterReviewItem(
  clipId: string,
  batchId: string,
  opts?: {
    sample_group?: string;
    status?: 'all' | 'reviewed' | 'unreviewed';
  },
): Promise<RouterReviewItemResponse> {
  const params = new URLSearchParams({ batch_id: batchId });
  if (opts?.sample_group) params.set('sample_group', opts.sample_group);
  if (opts?.status) params.set('status', opts.status);
  return request<RouterReviewItemResponse>(
    `/api/router-review/items/${encodeURIComponent(clipId)}?${params}`,
  );
}

export function saveRouterReviewLabel(
  clipId: string,
  batchId: string,
  body: RouterReviewLabelCreate,
): Promise<RouterReviewLabel> {
  const params = new URLSearchParams({ batch_id: batchId });
  return request<RouterReviewLabel>(
    `/api/router-review/items/${encodeURIComponent(clipId)}/label?${params}`,
    {
      method: 'POST',
      body: JSON.stringify(body),
    },
  );
}

// ── 대화형 튜토리얼 ───────────────────────────────────────────────
export interface TutorialLessonMeta {
  position: number;
  title: string;
  learning_objective: string;
  state: 'locked' | 'available' | 'in_progress' | 'completed';
}
export interface TutorialOverview {
  tutorial: TutorialAccess;
  set: { version: string; title: string } | null;
  lessons: TutorialLessonMeta[];
  current_run_no: number;
}
export interface TutorialReference {
  gt: GroundTruthInput;
  vlm_review: VlmReviewInput;
}
export interface TutorialLessonView {
  position: number;
  title: string;
  learning_objective: string;
  pre_submit_tip: string | null;
  clip: { id: string; duration_sec: number | null; started_at: string | null };
  attempt: {
    stage: TutorialAttemptStage;
    submitted_gt: GroundTruthInput | null;
    submitted_vlm_review: VlmReviewInput | null;
  } | null;
  // 아래 3개는 서버가 stage 에 따라서만 채운다(제출 전 미노출).
  prediction_snapshot?: Record<string, unknown>;
  reference?: TutorialReference;
  comparison?: TutorialComparison;
  feedback?: FeedbackContent;
}
export interface TutorialGtResult {
  prediction_snapshot: Record<string, unknown>;
}
export interface TutorialReviewResult {
  reference: TutorialReference;
  comparison: TutorialComparison;
  feedback: FeedbackContent;
}
export interface TutorialTeamMemberLesson {
  position: number;
  mismatch_count: number | null;
}
export interface TutorialTeamMember {
  user_id: string;
  display_name: string;
  email: string;
  status: 'not_started' | 'in_progress' | 'completed' | 'waived';
  completed_lessons: number;
  lessons: TutorialTeamMemberLesson[];
}
export interface TutorialTeamProgress {
  set: { version: string; title: string } | null;
  total_lessons: number;
  items: TutorialTeamMember[];
}

export function getTutorialOverview(): Promise<TutorialOverview> {
  return request<TutorialOverview>('/api/labeling-tutorial');
}
export function getTutorialLesson(position: number): Promise<TutorialLessonView> {
  return request<TutorialLessonView>(`/api/labeling-tutorial/lessons/${position}`);
}
export function saveTutorialGt(
  position: number,
  gt: GroundTruthInput,
): Promise<TutorialGtResult> {
  return request<TutorialGtResult>(`/api/labeling-tutorial/lessons/${position}/gt`, {
    method: 'POST',
    body: JSON.stringify(gt),
  });
}
export function saveTutorialVlmReview(
  position: number,
  review: VlmReviewInput,
): Promise<TutorialReviewResult> {
  return request<TutorialReviewResult>(
    `/api/labeling-tutorial/lessons/${position}/vlm-review`,
    { method: 'POST', body: JSON.stringify(review) },
  );
}
export function acknowledgeTutorialLesson(
  position: number,
): Promise<{ tutorial_completed: boolean }> {
  return request<{ tutorial_completed: boolean }>(
    `/api/labeling-tutorial/lessons/${position}/acknowledge`,
    { method: 'POST', body: '{}' },
  );
}
export async function getTutorialFileUrl(position: number): Promise<PlaybackUrl> {
  return resolveLocalUrl(
    await request<PlaybackUrl>(`/api/labeling-tutorial/lessons/${position}/file/url`),
  );
}
export async function getTutorialThumbnailUrl(position: number): Promise<PlaybackUrl> {
  return resolveLocalUrl(
    await request<PlaybackUrl>(`/api/labeling-tutorial/lessons/${position}/thumbnail/url`),
  );
}
export function getTutorialTeamProgress(): Promise<TutorialTeamProgress> {
  return request<TutorialTeamProgress>('/api/labeling-tutorial/team-progress');
}
export function resetTutorial(userId: string): Promise<{ progress: unknown }> {
  return request<{ progress: unknown }>(
    `/api/labeling-tutorial/users/${encodeURIComponent(userId)}/reset`,
    { method: 'POST', body: '{}' },
  );
}
export function waiveTutorial(userId: string, reason: string): Promise<{ progress: unknown }> {
  return request<{ progress: unknown }>(
    `/api/labeling-tutorial/users/${encodeURIComponent(userId)}/waive`,
    { method: 'POST', body: JSON.stringify({ reason }) },
  );
}

function resolveLocalUrl(r: PlaybackUrl): PlaybackUrl {
  if (r.type === 'local' && r.url.startsWith('/')) {
    return { ...r, url: `${BACKEND_URL}${r.url}` };
  }
  return r;
}
