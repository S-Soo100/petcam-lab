// 권한별 라벨링 웹 — 클라이언트/서버 공용 공개 타입 + 표시 문구(설계 §5·§6).
//
// 이 파일은 순수(no server-only)다. API 응답 모양과 라벨 상태/출처 표시 문구를 한곳에 두어
// 화면·매퍼·테스트가 같은 계약을 공유한다. 상대 제출·digest·reviewer UUID·r2_key 같은 blind
// 금지 필드는 애초에 이 타입에 존재하지 않는다(allowlist by construction).

// 영상 보관함 라벨 상태(설계 §6.1·§6.3) — 확정 전 라벨은 상태 문자열만 노출한다.
// re_review = 과거 clip 이 open canary 에 재편입돼 기존 라벨을 일시 숨긴 상태(review-fix P0-1).
export type PublicLabelState =
  | 'final'
  | 'awaiting'
  | 'owner_review'
  | 'unlabeled'
  | 're_review';

// 라벨 출처(설계 §6) — 새 이중 블라인드 합의와 기존 라벨을 같은 신뢰도로 위장하지 않는다.
export type PublicLabelSource =
  | 'blind_consensus'
  | 'owner_legacy'
  | 'single_legacy'
  | 'none';

// 라벨러 내 기록의 최종 합의 상태(설계 §5.2) — 개별 답·불일치를 숨기고 두 단계로만 접는다.
export type FinalStatus = 'confirmed' | 'in_review';

const LABEL_SOURCE_COPY: Record<PublicLabelSource, string> = {
  blind_consensus: '이중 확인 완료',
  owner_legacy: '기존 Owner 라벨',
  single_legacy: '기존 단일 라벨',
  none: '라벨 없음',
};

const LABEL_STATE_COPY: Record<PublicLabelState, string> = {
  final: '최종 라벨',
  awaiting: '라벨 확정 중',
  owner_review: 'Owner 검수 중',
  unlabeled: '미분류',
  re_review: '라벨 재검수 중',
};

export function labelSourceCopy(source: PublicLabelSource): string {
  return LABEL_SOURCE_COPY[source];
}

export function labelStateCopy(state: PublicLabelState): string {
  return LABEL_STATE_COPY[state];
}

export function finalStatusCopy(status: FinalStatus): string {
  return status === 'confirmed' ? '확정됨' : '검수 중';
}

// consensus 원시 상태(agreed/owner_resolved/awaiting/conflict/null)를 라벨러 안전 2단계로 접는다.
// conflict 도 in_review 로 접어 라벨러가 불일치 발생 여부조차 알 수 없게 한다(설계 §5.2 blind).
export function collapseFinalStatus(rawStatus: string | null | undefined): FinalStatus {
  return rawStatus === 'agreed' || rawStatus === 'owner_resolved' ? 'confirmed' : 'in_review';
}

// ── 공개 응답 아이템 ────────────────────────────────────────────────

// 라벨러 본인 blind 제출 기록 1건(설계 §5.2). 상대 원문 없음, final_status 는 2단계뿐.
export interface BlindHistoryItem {
  submission_id: string;
  clip_id: string;
  camera_id: string | null;
  camera_name: string | null;
  started_at: string;
  duration_sec: number;
  media_ready: boolean;
  submitted_at: string;
  decision: string;
  reason_code: string;
  initial_gt: unknown;
  note: string | null;
  cohort_kind: string;
  final_status: FinalStatus;
}

export interface BlindHistoryResponse {
  items: BlindHistoryItem[];
  next_cursor: string | null;
  has_more: boolean;
}

// 공용 영상 보관함 1건(설계 §5.3·§6). 확정 전 라벨은 final_decision/final_gt 가 null 이다.
export interface LabelingLibraryItem {
  clip_id: string;
  camera_id: string | null;
  camera_name: string | null;
  started_at: string;
  duration_sec: number;
  label_state: PublicLabelState;
  label_source: PublicLabelSource;
  final_decision: string | null;
  final_gt: unknown;
}

export interface LabelingLibraryResponse {
  items: LabelingLibraryItem[];
  next_cursor: string | null;
  has_more: boolean;
}

// Owner 운영 현황(설계 §7.1) — 집계만. reviewer UUID·이메일·개별 제출 body 없음.
export interface OwnerOverviewMember {
  display_name: string;
  submitted_count: number;
}

export interface OwnerOverviewGroup {
  group_id: string;
  group_name: string;
  clip_total: number;
  members: OwnerOverviewMember[];
  agreed_count: number;
  conflict_count: number;
  awaiting_count: number;
}

export interface OwnerOverviewCanary {
  cohort_id: string;
  label: string | null;
  group_id: string | null;
  clip_total: number;
  slot_total: number; // 진행률 분모(reviewer 2인이면 2×clip_total, review-fix P1-3)
  submitted_total: number;
  conflict_count: number;
}

export interface OwnerOverview {
  activity_day: string | null;
  groups: OwnerOverviewGroup[];
  open_canaries: OwnerOverviewCanary[];
}
