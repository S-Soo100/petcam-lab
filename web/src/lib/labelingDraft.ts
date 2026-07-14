'use client';

// 저장 전 입력의 브라우저 임시 저장(설계 §9.3 · 하드닝 §3·§4·§5).
//
// 서버에는 미완성 입력을 자동 저장하지 않는다. 같은 탭의 sessionStorage 에만 둔다.
// 사람 판정(gt)과 AI 검수(review)를 단계(phase)별로 분리 저장·복원·삭제한다:
//   - 사람 판정 저장 성공  → gt 임시본만 삭제(review 임시본은 건드리지 않음)
//   - AI 검수 제출 성공     → review 임시본만 삭제(다른 lesson 은 건드리지 않음)
//
// 안전 규칙:
// - 키에 user id + 콘텐츠 정체성(scope: tutorial set/lesson 또는 clip) + 단계(phase)를 포함한다.
//   tutorial-v1 과 tutorial-v2 가 같은 clip/position 을 재사용해도 scope 에 불변 tutorial set
//   identity 가 들어가 v1 임시본이 v2 에서 복원되지 않는다(하드닝 §3).
// - 손상·변조된 임시본은 구조 검증으로 걸러 조용히 폐기하고 storage 에서도 삭제한다(하드닝 §5).
// - 버전/user/phase 불일치 임시본도 폐기한다. 다른 사용자의 임시본은 절대 복원하지 않는다.
//
// 순수 함수(key/serialize/parse/read/write/clear)로 계약을 고정하고 테스트한다. hook 은 얇은 배선.

import { useCallback, useEffect, useRef } from 'react';

import {
  isValidGroundTruthShape,
  isValidSelectedFields,
  isValidVlmReviewShape,
  type GroundTruthField,
  type GroundTruthInput,
  type VlmReviewInput,
} from './labelingV2';

// 키 구조·payload(단계 분리)를 바꿨으므로 버전을 올린다. 과거 v1 임시본은 자동으로 무시된다.
const DRAFT_VERSION = 2 as const;

export type DraftPhase = 'gt' | 'review';

export interface GtDraft {
  v: typeof DRAFT_VERSION;
  userId: string;
  phase: 'gt';
  gt: GroundTruthInput;
  selected: GroundTruthField[];
  savedAt: string;
}

export interface ReviewDraft {
  v: typeof DRAFT_VERSION;
  userId: string;
  phase: 'review';
  review: VlmReviewInput;
  savedAt: string;
}

// sessionStorage 최소 인터페이스 — 테스트에서 fake storage 를 주입할 수 있게 좁힌다.
export type DraftStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

// 키: user id + scope(콘텐츠 정체성) + phase. scope 예) `tutorial:${setId}:${position}` · `clip:${clipId}`.
export function draftKey(userId: string, scope: string, phase: DraftPhase): string {
  return `petcam-labeling-draft:v${DRAFT_VERSION}:${userId}:${scope}:${phase}`;
}

export function serializeDraft(draft: GtDraft | ReviewDraft): string {
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

// 공통 봉투 검증: 버전·user·phase. 하나라도 어긋나면 null(조용히 폐기).
function checkEnvelope(
  d: Record<string, unknown>,
  expectedUserId: string,
  expectedPhase: DraftPhase,
): boolean {
  if (d.v !== DRAFT_VERSION) return false;
  if (d.phase !== expectedPhase) return false;
  // 다른 사용자의 임시본은 절대 복원하지 않는다(§9.3).
  if (d.userId !== expectedUserId) return false;
  return true;
}

// 원시 문자열 → gt 임시본. 봉투/구조 오류는 null. 미완성 draft 는 구조만 맞으면 허용(하드닝 §5).
export function parseGtDraft(raw: string | null, expectedUserId: string): GtDraft | null {
  const d = parseJsonObject(raw);
  if (!d) return null;
  if (!checkEnvelope(d, expectedUserId, 'gt')) return null;
  if (!isValidGroundTruthShape(d.gt)) return null;
  if (!isValidSelectedFields(d.selected)) return null;
  return d as unknown as GtDraft;
}

export function parseReviewDraft(raw: string | null, expectedUserId: string): ReviewDraft | null {
  const d = parseJsonObject(raw);
  if (!d) return null;
  if (!checkEnvelope(d, expectedUserId, 'review')) return null;
  if (!isValidVlmReviewShape(d.review)) return null;
  return d as unknown as ReviewDraft;
}

// 읽기 — 손상/버전/user/phase 오류면 해당 키를 storage 에서 제거하고 null.
function readWith<T>(
  storage: DraftStorage,
  key: string,
  parse: (raw: string | null) => T | null,
): T | null {
  let raw: string | null;
  try {
    raw = storage.getItem(key);
  } catch {
    return null;
  }
  const draft = parse(raw);
  if (raw && !draft) {
    // parse/version/user/phase/구조 오류 임시본은 조용히 폐기(storage 에서도 삭제, 하드닝 §5).
    try {
      storage.removeItem(key);
    } catch {
      /* 무시 — 조회 실패는 제출을 막지 않는다 */
    }
  }
  return draft;
}

export function readGtDraft(storage: DraftStorage, key: string, userId: string): GtDraft | null {
  return readWith(storage, key, (raw) => parseGtDraft(raw, userId));
}

export function readReviewDraft(
  storage: DraftStorage,
  key: string,
  userId: string,
): ReviewDraft | null {
  return readWith(storage, key, (raw) => parseReviewDraft(raw, userId));
}

// 쓰기 — 성공 여부 반환(실패 시 hook 이 한 번만 사용자에게 알린다, §11).
export function writeDraft(
  storage: DraftStorage,
  key: string,
  draft: GtDraft | ReviewDraft,
): boolean {
  try {
    storage.setItem(key, serializeDraft(draft));
    return true;
  } catch {
    return false;
  }
}

export function clearDraft(storage: DraftStorage, key: string): void {
  try {
    storage.removeItem(key);
  } catch {
    /* 무시 */
  }
}

function getSessionStorage(): DraftStorage | null {
  try {
    if (typeof window === 'undefined') return null;
    return window.sessionStorage;
  } catch {
    return null;
  }
}

// ── React hook ────────────────────────────────────────────────────
// phase 에 따라 gt 또는 review 임시본을 debounce 저장하고, 해당 단계 진입 시 한 번만 복원한다.
// gt 저장·review 제출 성공 시 각각 clearGt/clearReview 로 해당 임시본만 삭제한다.
// 순수 로직(위)만 테스트하고, 이 hook 은 얇은 배선으로 유지한다.
export function useLabelingDraft(params: {
  userId: string | null;
  scope: string | null;
  // 'gt'(사람 판정 편집) | 'review'(AI 검수 편집) | null(로딩/완료 — 비활성).
  // 페이지가 로드 완료 후에만 non-null 을 넘겨 load 가 복원본을 덮어쓰지 않게 한다.
  phase: DraftPhase | null;
  gt: GroundTruthInput;
  selected: ReadonlySet<GroundTruthField>;
  review: VlmReviewInput;
  onRestoreGt: (draft: GtDraft) => void;
  onRestoreReview: (draft: ReviewDraft) => void;
  onRestored: () => void;
  onWriteError: () => void;
}): { clearGt: () => void; clearReview: () => void } {
  const { userId, scope, phase } = params;

  // 콜백은 ref 로 잡아 effect 의존성에서 뺀다(재실행 유발 방지).
  const cbRef = useRef(params);
  cbRef.current = params;

  const ready = !!userId && !!scope && phase !== null;
  const gtKey = userId && scope ? draftKey(userId, scope, 'gt') : null;
  const reviewKey = userId && scope ? draftKey(userId, scope, 'review') : null;

  // 복원은 (key,phase)당 한 번만. clear 후에도 재복원하지 않도록 표시.
  const restoredKeys = useRef<Set<string>>(new Set());
  const warned = useRef(false);

  // 복원: 활성 phase 의 임시본을 그 phase 에서 한 번만.
  useEffect(() => {
    if (!ready || !userId) return;
    const storage = getSessionStorage();
    if (!storage) return;
    if (phase === 'gt' && gtKey && !restoredKeys.current.has(gtKey)) {
      restoredKeys.current.add(gtKey);
      const draft = readGtDraft(storage, gtKey, userId);
      if (draft) {
        cbRef.current.onRestoreGt(draft);
        cbRef.current.onRestored();
      }
    }
    if (phase === 'review' && reviewKey && !restoredKeys.current.has(reviewKey)) {
      restoredKeys.current.add(reviewKey);
      const draft = readReviewDraft(storage, reviewKey, userId);
      if (draft) {
        cbRef.current.onRestoreReview(draft);
        cbRef.current.onRestored();
      }
    }
  }, [ready, phase, gtKey, reviewKey, userId]);

  // 저장: 활성 phase 의 입력 변경 시 debounce.
  useEffect(() => {
    if (!ready || !userId) return;
    const storage = getSessionStorage();
    if (!storage) return;
    const handle = setTimeout(() => {
      let ok = true;
      if (phase === 'gt' && gtKey) {
        ok = writeDraft(storage, gtKey, {
          v: DRAFT_VERSION,
          userId,
          phase: 'gt',
          gt: params.gt,
          selected: Array.from(params.selected),
          savedAt: new Date().toISOString(),
        });
      } else if (phase === 'review' && reviewKey) {
        ok = writeDraft(storage, reviewKey, {
          v: DRAFT_VERSION,
          userId,
          phase: 'review',
          review: params.review,
          savedAt: new Date().toISOString(),
        });
      }
      if (!ok && !warned.current) {
        warned.current = true;
        cbRef.current.onWriteError();
      }
    }, 500);
    return () => clearTimeout(handle);
    // gt/selected/review 를 개별 나열해 값 변경마다 저장한다.
  }, [ready, phase, gtKey, reviewKey, userId, params.gt, params.selected, params.review]);

  const clearGt = useCallback(() => {
    if (!gtKey) return;
    const storage = getSessionStorage();
    if (storage) clearDraft(storage, gtKey);
    restoredKeys.current.add(gtKey); // 저장 성공 후 즉시 재복원 방지.
  }, [gtKey]);

  const clearReview = useCallback(() => {
    if (!reviewKey) return;
    const storage = getSessionStorage();
    if (storage) clearDraft(storage, reviewKey);
    restoredKeys.current.add(reviewKey);
  }, [reviewKey]);

  return { clearGt, clearReview };
}
