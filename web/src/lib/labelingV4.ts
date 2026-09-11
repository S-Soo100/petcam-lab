// web/src/lib/labelingV4.ts — v4 공개 계약(순수).
import type { HighlightDetail, HighlightInitialStatus, HighlightSource } from './highlightV4';

export type V4Scope = 'mine' | 'all';
export type V4LabelState = 'unlabeled' | 'labeled';
export type V4HighlightState = 'yes' | 'no' | 'pending';
// 행동 표시 4종(2026-09-11, 스펙 feature-behavior-marks). 하이라이트 O/X 와 무관, 영상당 종류별 1개, 종류끼리 독립.
// ⚠️ 미표시 = 미확인(음성 아님). 옛 ✨ 데이터는 전부 meaningful.
export type V4BehaviorKind = 'meaningful' | 'wheel' | 'fall' | 'closeup';
export const V4_BEHAVIOR_KINDS: V4BehaviorKind[] = ['meaningful', 'wheel', 'fall', 'closeup'];
export const V4_BEHAVIOR_KIND_LABELS: Record<V4BehaviorKind, string> = { meaningful: '의미있는 행동', wheel: '쳇바퀴', fall: '추락', closeup: '예쁘게 나옴' };
export const V4_BEHAVIOR_KIND_ICONS: Record<V4BehaviorKind, string> = { meaningful: '✨', wheel: '🎡', fall: '⚠️', closeup: '📸' };
export const V4_BEHAVIOR_KIND_HINTS: Record<V4BehaviorKind, string> = {
  meaningful: '물·허물·밥 등 — 쳇바퀴·추락·예쁘게는 그쪽 버튼',
  wheel: '쳇바퀴 탐 — 앱 대표 우선, 밤당 1개',
  fall: '떨어짐 — 수집용, 앱 대표엔 안 감',
  closeup: '크고 예쁘게 나옴 — 자동 클로즈업 검증용',
};
export function isBehaviorKind(v: unknown): v is V4BehaviorKind {
  return typeof v === 'string' && (V4_BEHAVIOR_KINDS as string[]).includes(v);
}
// 목록 필터 — 어느 종류든('yes') 또는 특정 종류.
export type V4BehaviorFlagFilter = 'yes' | V4BehaviorKind;

// 종류 하나의 표시 상태(옛 이름 유지 — meaningful 은 behavior_flag 로도 계속 노출).
export interface V4BehaviorFlag {
  flagged: boolean;
  flagged_by_name: string | null;
  flagged_at: string | null;
}
export type V4BehaviorMarks = Record<V4BehaviorKind, V4BehaviorFlag>;
export const EMPTY_BEHAVIOR_FLAG: V4BehaviorFlag = { flagged: false, flagged_by_name: null, flagged_at: null };

export interface V4ClipHighlight {
  source: HighlightSource;
  status: HighlightInitialStatus;
  value: boolean | null;
  reason: string;
  reviewer_name: string | null;
  decided_at: string | null;
}

// ── ⭐ 대표 tier(2026-09-10, 스펙 feature-highlight-featured-tier) — O/X 위에 조회 시 계산되는 하루 상한 레이어.
// 상수는 DB 함수(fn_highlight_featured) 기본값·petcam-api 와 같은 값(바꾸면 세 곳 같이, 런북 §6.y).
export type V4FeaturedTier = 'featured' | 'candidate';
export interface V4FeaturedInfo {
  tier: V4FeaturedTier;
  day_key: string; // 'YYYY-MM-DD' — 20:00 KST 경계 하루
  episode_rank: number;
  // 대표 클립의 KST 시(hour) 안에서의 사건 순위 — FEATURED_HOUR_CAP 를 넘으면 후보(v0.1, 2026-09-11).
  episode_hour_rank: number;
  episode_clip_count: number;
  episode_activity_sec: number;
  is_representative: boolean;
  top_n: number | null; // null = 하루 상한 없음
}
// v0.1(2026-09-11 owner): 10분 묶기 · 같은 시간대 최대 3 · 하루 상한 없음.
export const FEATURED_TOP_N: number | null = null;
export const FEATURED_HOUR_CAP = 3;
export const FEATURED_DAY_CAP = 15; // 하루·카메라당 대표 예산(owner 2026-09-11, 임시)
export const FEATURED_GAP_SEC = 600;
// jitter 의심 회귀 세트(정지 게코 bbox 흔들림 서명) — 목록 `🔎 의심 서명` 칩. 검수 우선순위 + 2.6.1 전후 비교용.
export const JITTER_SAMPLE_ID = 'jitter-2026-09';
export const V4_JITTER_SAMPLE_LABEL = '의심 서명';
export const FEATURED_DAY_START_HOUR = 20;
export const FEATURED_DAYS = 7;
export const FEATURED_MAX_DAYS = 31;
export const FEATURED_TZ = 'Asia/Seoul';
export const V4_FEATURED_LABEL = '대표만';

export function featuredBadgeText(f: V4FeaturedInfo | null): string | null {
  if (!f) return null;
  return f.tier === 'featured' ? `⭐ 대표 ${f.episode_rank}위` : '후보';
}

export function featuredLineText(f: V4FeaturedInfo | null): string | null {
  if (!f) return null;
  const ep = `사건 ${f.episode_clip_count}클립 · 움직임 ${f.episode_activity_sec}초`;
  if (f.tier === 'featured') return `⭐ 이 날 대표 ${f.episode_rank}위 · ${ep}`;
  if (!f.is_representative) return `후보 · 같은 사건의 다른 클립(사건 ${f.episode_rank}위) · ${ep}`;
  return `후보 · 사건 ${f.episode_rank}위 · ${ep}`;
}

export interface V4ClipItem {
  id: string;
  camera_id: string | null;
  camera_name: string;
  started_at: string;
  duration_sec: number | null;
  media_ready: boolean;
  highlight: V4ClipHighlight;
  behavior_flag: V4BehaviorFlag; // = meaningful(호환)
  // 표시 종류 배열(카드 배지). route 가 배치 RPC 로 붙인다(실패 시 []).
  behavior_kinds: V4BehaviorKind[];
  // 목록 카드 썸네일(짧은 서명 URL). 없으면 null(UX ⑦).
  thumbnail_url: string | null;
  // ⭐ 대표 tier — 현재 O 인 항목에만(보조 정보, 계산 실패·범위 밖이면 null).
  featured: V4FeaturedInfo | null;
}

export interface V4ClipListResponse {
  items: V4ClipItem[];
  next_cursor: string | null;
  has_more: boolean;
}

export interface V4ListFilters {
  scope: V4Scope;
  cameraIds?: string[];
  labelState?: V4LabelState | null;
  highlightState?: V4HighlightState | null;
  behaviorFlag?: V4BehaviorFlagFilter | null;
  sampleId?: string | null;
  cursor?: string | null;
  limit?: number;
}

export interface V4ClipDetail {
  id: string;
  camera_id: string | null;
  started_at: string;
  duration_sec: number | null;
  media_ready: boolean;
  highlight: HighlightDetail;
  behavior_flag: V4BehaviorFlag; // = behavior_marks.meaningful(호환)
  behavior_marks: V4BehaviorMarks;
  // ⭐ 대표 tier — 현재 O 일 때만(그 클립의 하루 창 기준). 아니면 null.
  featured: V4FeaturedInfo | null;
}

export interface V4CameraOption { id: string; name: string; assigned: boolean }

export interface V4Member { user_id: string; display_name: string; camera_ids: string[] }

export interface V4Overview {
  activity_day: string | null;
  unlabeled_total: number;
  labeled_today: number;
  labeled_7d: number;
  members: { user_id: string; display_name: string; labeled_7d: number }[]; // owner 전용 화면 — UUID 노출 OK
  cameras: { camera_name: string; unlabeled: number; labeled_7d: number }[];
  // 활성 GME 계약으로 succeeded run 이 있는 영상 비율(2.6.1 전환 타이밍용). RPC 실패면 null.
  coverage: V4ContractCoverage | null;
}

export interface V4ContractCoverage {
  last7d_total: number;
  last7d_with_run: number;
  all_total: number;
  all_with_run: number;
}

export function coveragePercent(withRun: number, total: number): number | null {
  return total > 0 ? Math.round((withRun / total) * 100) : null;
}

export const V4_LABEL_STATE_LABELS: Record<V4LabelState, string> = { unlabeled: '라벨 안 됨', labeled: '라벨 됨' };
export const V4_HIGHLIGHT_STATE_LABELS: Record<V4HighlightState, string> = { yes: '하이라이트 O', no: '하이라이트 X', pending: '분석 대기' };

export const V4_BEHAVIOR_FLAG_LABEL = '의미있는 행동';

// 봉인 평가 표본(2.6.1 준비): 목록 `?sample=<id>` 필터. 활성 표본 id 는 env 로 바꾸고 기본은 eval-2026-09.
export const EVAL_SAMPLE_ID_RE = /^[a-z0-9-]{3,40}$/;
export const ACTIVE_EVAL_SAMPLE_ID = (process.env.NEXT_PUBLIC_LABELING_EVAL_SAMPLE_ID || 'eval-2026-09').trim();
export const V4_EVAL_SAMPLE_LABEL = '평가 표본';
export const EVAL_SAMPLE_STORAGE_KEY = 'labeling.v4.sample';
export interface V4EvalSampleProgress { sample_id: string; total: number; labeled: number }
export function isEvalSampleId(v: unknown): v is string {
  return typeof v === 'string' && EVAL_SAMPLE_ID_RE.test(v);
}

// 체크된 영상 → 기존 행동 GT 라벨링 화면(motion v3 상세). 2026-09-08 owner 결정으로 승인 라벨러에게도
// 열렸다(labelingRouteAccess shared + API requireLabelingAccess + fn_lock_motion_clip_gt 개방).
export function behaviorGtPath(clipId: string): string {
  return `/labeling/motion/${clipId}`;
}

export function v4DetailPath(clipId: string): string {
  return `/labeling/v4/${clipId}`;
}
