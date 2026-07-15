// 라벨링 후보 격리함 — 공유 순수 계약(설계 §5, §6, §7).
//
// 이 모듈은 브라우저/서버 어디서나 import 가능한 순수 로직만 둔다.
// - 유효 상태 판정(effectiveTriageState): owner 결정이 시스템 제안보다 항상 우선.
// - 표시 문구(triageReasonLabel): 사전 정의한 한국어만. raw evidence/threshold 는 절대 노출 안 함.
// - owner-safe 응답 타입: evidence_snapshot·provenance 원문을 담지 않는다.
//
// DB 조회/커서/Buffer 같은 server 전용 로직은 labelingTriageServer.ts 에 둔다.

export type TriageSuggestedRoute = 'label' | 'quarantine';
export type TriageSuggestionReason =
  | 'gate_active'
  | 'gate_absent'
  | 'gate_static'
  | 'manual';
export type TriageOwnerDecision = 'label' | 'skip';

// 본 라벨링 큐/격리함이 함께 쓰는 유효 상태.
// pending=검토 필요, skipped=라벨링 안 함, labeled=라벨링으로 보냄, queue=본 큐 유지.
export type EffectiveTriageState = 'pending' | 'skipped' | 'labeled' | 'queue';

export interface TriageStateInput {
  readonly suggested_route: TriageSuggestedRoute;
  readonly owner_decision: TriageOwnerDecision | null;
}

// 유효 상태 우선순위(설계 §5.2). owner 결정이 최상위이고, triage row 가 없으면 본 큐다.
export function effectiveTriageState(
  row: TriageStateInput | null,
): EffectiveTriageState {
  if (row === null) return 'queue';
  // owner 결정이 있으면 시스템 제안과 무관하게 결정을 따른다.
  if (row.owner_decision === 'label') return 'labeled';
  if (row.owner_decision === 'skip') return 'skipped';
  // owner 미결정 — 시스템 제안으로 판정.
  if (row.suggested_route === 'quarantine') return 'pending';
  return 'queue';
}

// 유효 상태가 본 큐에서 제외되는지 여부(pending/skipped 만 제외). queue/labeled 는 포함.
export function isHiddenFromLabelingQueue(state: EffectiveTriageState): boolean {
  return state === 'pending' || state === 'skipped';
}

// 격리함에 노출하는 사전 정의 문구(설계 §7). gate_active 는 label 라우팅용 내부
// provenance 라 격리함 카드에 뜨지 않지만, 타입 exhaustive 를 위해 중립 문구를 둔다.
export function triageReasonLabel(reason: TriageSuggestionReason): string {
  switch (reason) {
    case 'gate_absent':
      return '게코가 보이지 않을 가능성이 높음';
    case 'gate_static':
      return '게코가 보이지만 움직임이 거의 없을 가능성이 높음';
    case 'manual':
      return 'owner가 직접 검토 대상으로 보냄';
    case 'gate_active':
      // 본 큐 유지용 내부 provenance — 실제 격리함 목록/상세에는 노출되지 않는다.
      return '시스템이 활동으로 판정함';
    default: {
      const exhaustive: never = reason;
      return exhaustive;
    }
  }
}

// ── owner-safe 응답 타입 ─────────────────────────────────────────
// evidence_snapshot, 로컬 경로, producer host 등 raw provenance 는 담지 않는다.

export interface TriageListItem {
  readonly clip_id: string;
  readonly camera_id: string | null;
  readonly started_at: string;
  readonly duration_sec: number | null;
  readonly suggested_route: TriageSuggestedRoute;
  readonly reason: TriageSuggestionReason;
  readonly reason_label: string;
  readonly owner_decision: TriageOwnerDecision | null;
  readonly effective_state: EffectiveTriageState;
  readonly updated_at: string;
}

// 상세는 목록 + 최소 provenance(정책 버전/소스)까지. evidence_snapshot 은 여전히 제외(설계 §8.2).
export interface TriageDetail extends TriageListItem {
  readonly suggestion_source: string;
  readonly policy_version: string;
  readonly decided_at: string | null;
  readonly decision_note: string | null;
}

// 커서 payload — updated_at DESC, clip_id DESC 안정 정렬용(설계 §8.1).
export interface TriageCursor {
  readonly updatedAt: string;
  readonly clipId: string;
}
