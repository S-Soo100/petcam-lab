'use client';

// 저장 전 입력의 브라우저 임시 저장(설계 §9.3).
//
// 서버에는 미완성 GT 를 자동 저장하지 않는다. 같은 탭의 sessionStorage 에만 둔다.
// 목적: 페이지 이동·창 복귀·토큰 갱신·새로고침 뒤에도 저장 전 입력을 복원한다(§9.1 인증 이벤트
// 처리와 짝). 순수 함수(key/serialize/parse/read/write/clear)로 계약을 고정하고 테스트한다.
//
// 안전 규칙(§9.3):
// - 키에 user id + 콘텐츠 정체성(scope)을 포함해 다른 사용자·다른 lesson 의 임시본을 복원하지 않는다.
// - 버전/parse 오류가 난 임시본은 조용히 폐기하고 빈 폼으로 시작한다.
// - GT 저장·VLM 제출·완료 시 해당 임시본을 삭제한다(hook 의 clear).

import { useCallback, useEffect, useRef } from 'react';

import type {
  GroundTruthField,
  GroundTruthInput,
  VlmReviewInput,
} from './labelingV2';

const DRAFT_VERSION = 1 as const;

export interface LabelingDraft {
  v: typeof DRAFT_VERSION;
  userId: string;
  gt: GroundTruthInput;
  selected: GroundTruthField[];
  review: VlmReviewInput | null;
  savedAt: string;
}

// sessionStorage 최소 인터페이스 — 테스트에서 fake storage 를 주입할 수 있게 좁힌다.
export type DraftStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

// 키: user id + scope(콘텐츠 정체성). scope 예) `tutorial:${clipId}:${position}` · `clip:${clipId}`.
export function draftKey(userId: string, scope: string): string {
  return `petcam-labeling-draft:v${DRAFT_VERSION}:${userId}:${scope}`;
}

export function serializeDraft(draft: LabelingDraft): string {
  return JSON.stringify(draft);
}

// 원시 문자열 → draft. 버전 불일치·user 불일치·parse 오류는 null(조용히 폐기).
export function parseDraft(raw: string | null, expectedUserId: string): LabelingDraft | null {
  if (!raw) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!parsed || typeof parsed !== 'object') return null;
  const d = parsed as Partial<LabelingDraft>;
  if (d.v !== DRAFT_VERSION) return null;
  // 다른 사용자의 임시본은 절대 복원하지 않는다(§9.3).
  if (d.userId !== expectedUserId) return null;
  if (!d.gt || typeof d.gt !== 'object') return null;
  if (!Array.isArray(d.selected)) return null;
  return d as LabelingDraft;
}

// 읽기 — 손상/버전불일치/타 사용자면 해당 키를 제거하고 null.
export function readDraft(
  storage: DraftStorage,
  key: string,
  expectedUserId: string,
): LabelingDraft | null {
  let raw: string | null;
  try {
    raw = storage.getItem(key);
  } catch {
    return null;
  }
  const draft = parseDraft(raw, expectedUserId);
  if (raw && !draft) {
    // parse/version/user 오류 임시본은 조용히 폐기.
    try {
      storage.removeItem(key);
    } catch {
      /* 무시 — 조회 실패는 제출을 막지 않는다 */
    }
  }
  return draft;
}

// 쓰기 — 성공 여부를 반환한다(실패 시 hook 이 한 번만 사용자에게 알린다, §11).
export function writeDraft(storage: DraftStorage, key: string, draft: LabelingDraft): boolean {
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
// 페이지가 소유한 GT/selected/review 를 debounce 로 임시 저장하고, draft 단계 진입 시 복원한다.
// 순수 로직(위)만 테스트하고, 이 hook 은 얇은 배선으로 유지한다.
export function useLabelingDraft(params: {
  // lesson/clip 로드 완료 && 아직 저장 전(draft) 단계일 때만 동작한다.
  enabled: boolean;
  userId: string | null;
  scope: string | null;
  gt: GroundTruthInput;
  selected: ReadonlySet<GroundTruthField>;
  review: VlmReviewInput | null;
  onRestore: (draft: LabelingDraft) => void;
  onRestored: () => void;
  onWriteError: () => void;
}): { clear: () => void } {
  const { enabled, userId, scope } = params;

  // 콜백은 ref 로 잡아 effect 의존성에서 뺀다(재실행 유발 방지).
  const cbRef = useRef(params);
  cbRef.current = params;

  const active = enabled && !!userId && !!scope;
  const key = active ? draftKey(userId as string, scope as string) : null;

  // 복원: 이 scope 에서 한 번만. 사용자가 편집을 시작한 뒤 다시 덮어쓰지 않는다.
  const restoredForKey = useRef<string | null>(null);
  const warnedForKey = useRef<string | null>(null);
  useEffect(() => {
    if (!active || !key || !userId) return;
    if (restoredForKey.current === key) return;
    restoredForKey.current = key;
    const storage = getSessionStorage();
    if (!storage) return;
    const draft = readDraft(storage, key, userId);
    if (draft) {
      cbRef.current.onRestore(draft);
      cbRef.current.onRestored();
    }
  }, [active, key, userId]);

  // 저장: gt/selected/review 변경 시 debounce.
  useEffect(() => {
    if (!active || !key || !userId) return;
    const storage = getSessionStorage();
    if (!storage) return;
    const handle = setTimeout(() => {
      const ok = writeDraft(storage, key, {
        v: DRAFT_VERSION,
        userId,
        gt: params.gt,
        selected: Array.from(params.selected),
        review: params.review,
        savedAt: new Date().toISOString(),
      });
      if (!ok && warnedForKey.current !== key) {
        warnedForKey.current = key;
        cbRef.current.onWriteError();
      }
    }, 500);
    return () => clearTimeout(handle);
    // params.gt/selected/review 를 개별 나열해 값 변경마다 저장한다.
  }, [active, key, userId, params.gt, params.selected, params.review]);

  const clear = useCallback(() => {
    if (!key) return;
    const storage = getSessionStorage();
    if (storage) clearDraft(storage, key);
    // 저장 성공 후 즉시 재복원되지 않게 이 scope 는 복원 완료로 표시.
    restoredForKey.current = key;
  }, [key]);

  return { clear };
}
