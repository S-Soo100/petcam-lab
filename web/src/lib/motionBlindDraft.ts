// 이중 블라인드 라벨 입력의 브라우저 임시 저장(하드닝 §5). labelingDraft.ts 의 fail-soft 패턴을 따른다.
//
// 저장 대상은 decision·reasonCode·gt·selected(+scope·version) 뿐이다. lease token, 상대 제출,
// VLM, Python Evidence, R2 key, auth token 은 절대 저장하지 않는다(설계 §5.1). 복원한 draft 는
// 기존 claim 흐름으로 새 lease 를 다시 받는다 — 토큰은 draft 에 들어오지 않는다.
//
// 격리 키·봉투에 user + clip + cohort(kind/id) + comparator version 을 넣어 다른 사용자·clip·
// cohort·버전의 임시본이 복원되지 않게 한다. 손상/변조/버전 불일치/duration 초과 segment 는 조용히
// 폐기하고 storage 에서도 삭제한다. draft 는 미완성일 수 있으므로 완결성(관찰 필수 등)은 검증하지 않고
// 구조(shape)와 segment 의 실제 영상 길이 적합성만 확인한다.
//
// 순수 함수(key/serialize/parse/read/write/clear)로 계약을 고정하고 테스트한다. 컴포넌트는 얇은 배선.

import {
  isValidGroundTruthShape,
  isValidSelectedFields,
  type GroundTruthField,
  type GroundTruthInput,
} from './labelingV2';
import { type BlindDecision, type BlindReasonCode } from './motionBlindReview';

export const BLIND_DRAFT_VERSION = 1 as const;

const DECISIONS: readonly BlindDecision[] = ['label', 'hold', 'exclude'];
const REASON_CODES: readonly BlindReasonCode[] = [
  'behavior_data',
  'ambiguous',
  'gecko_absent',
  'capture_error',
  'media_error',
];

export type BlindCohortKind = 'live' | 'canary';

// 복원 대상 scope 정체성. 키·봉투가 이 다섯 값으로 격리된다.
export interface BlindDraftScope {
  userId: string;
  clipId: string;
  cohortKind: BlindCohortKind;
  cohortId: string | null;
  comparatorVersion: 'motion-blind-v1';
}

export interface BlindDraftV1 extends BlindDraftScope {
  v: typeof BLIND_DRAFT_VERSION;
  decision: BlindDecision | null;
  reasonCode: BlindReasonCode;
  gt: GroundTruthInput;
  selected: GroundTruthField[];
  savedAt: string;
}

// sessionStorage 최소 인터페이스 — 테스트에서 fake storage 를 주입할 수 있게 좁힌다.
export type BlindDraftStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

// 키: user + clip + cohort kind/id + comparator version. cohortId 없으면(live) 'live' 로 표기.
export function blindDraftKey(
  userId: string,
  clipId: string,
  cohortKind: BlindCohortKind,
  cohortId: string | null,
  comparatorVersion: 'motion-blind-v1',
): string {
  return `petcam-blind-draft:v${BLIND_DRAFT_VERSION}:${userId}:${clipId}:${cohortKind}:${cohortId ?? 'live'}:${comparatorVersion}`;
}

export function serializeBlindDraft(draft: BlindDraftV1): string {
  return JSON.stringify(draft);
}

function parseJsonObject(raw: string | null): Record<string, unknown> | null {
  if (!raw) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null;
  return parsed as Record<string, unknown>;
}

// segment 가 실제 영상 길이 안에 있는지(0 <= start < end <= duration). 완결성은 보지 않되 duration 을
// 넘는 segment 는 stale(영상 교체/길이 오인)로 보고 폐기한다(하드닝: GT_DURATION_CAP 제거와 정합).
function segmentsWithinDuration(gt: GroundTruthInput, duration: number): boolean {
  return gt.segments.every(
    (s) => s.start_sec >= 0 && s.start_sec < s.end_sec && s.end_sec <= duration,
  );
}

// 원시 문자열 → blind draft. 봉투(버전/user/clip/cohort/comparator)·구조·duration 오류는 null.
export function parseBlindDraft(
  raw: string | null,
  expected: BlindDraftScope,
  duration: number,
): BlindDraftV1 | null {
  const d = parseJsonObject(raw);
  if (!d) return null;
  // 봉투: 버전·scope 정체성 일치. 하나라도 어긋나면 폐기(다른 user/clip/cohort/version 복원 금지).
  if (d.v !== BLIND_DRAFT_VERSION) return null;
  if (d.userId !== expected.userId) return null;
  if (d.clipId !== expected.clipId) return null;
  if (d.cohortKind !== expected.cohortKind) return null;
  if ((d.cohortId ?? null) !== (expected.cohortId ?? null)) return null;
  if (d.comparatorVersion !== expected.comparatorVersion) return null;
  // 구조: decision(null 허용)·reasonCode·gt·selected.
  if (d.decision !== null && !DECISIONS.includes(d.decision as BlindDecision)) return null;
  if (!REASON_CODES.includes(d.reasonCode as BlindReasonCode)) return null;
  if (!isValidGroundTruthShape(d.gt)) return null;
  if (!isValidSelectedFields(d.selected)) return null;
  if (!segmentsWithinDuration(d.gt as GroundTruthInput, duration)) return null;
  return d as unknown as BlindDraftV1;
}

// 읽기 — 손상/봉투/구조/duration 오류면 해당 키를 storage 에서 제거하고 null(조용히 폐기).
export function readBlindDraft(
  storage: BlindDraftStorage,
  key: string,
  expected: BlindDraftScope,
  duration: number,
): BlindDraftV1 | null {
  let raw: string | null;
  try {
    raw = storage.getItem(key);
  } catch {
    return null;
  }
  const draft = parseBlindDraft(raw, expected, duration);
  if (raw && !draft) {
    try {
      storage.removeItem(key);
    } catch {
      /* 무시 — 조회 실패는 제출을 막지 않는다 */
    }
  }
  return draft;
}

// 쓰기 — 성공 여부 반환(실패 시 호출부가 한 번만 사용자에게 알린다).
export function writeBlindDraft(storage: BlindDraftStorage, key: string, draft: BlindDraftV1): boolean {
  try {
    storage.setItem(key, serializeBlindDraft(draft));
    return true;
  } catch {
    return false;
  }
}

export function clearBlindDraft(storage: BlindDraftStorage, key: string): void {
  try {
    storage.removeItem(key);
  } catch {
    /* 무시 */
  }
}
