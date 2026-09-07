// 라벨러 진행 수(UX ③) — 목록에서 서버 집계를 받아 sessionStorage 에 두고, 상세에서 확정할 때마다 로컬로 +1/-1 한다.
// 상세마다 서버 집계를 다시 부르면 무거워서(전체 clip 스캔), 목록 방문 때만 새로 받는다.
'use client';

export interface V4Progress {
  activity_day: string | null;
  labeled_today_me: number;
  labeled_today_all: number;
  unlabeled_all: number;
  unlabeled_mine: number | null; // 배정 카메라 없으면 null
  fetched_at: number; // epoch ms
}

const KEY = 'labeling.v4.progress';
export const PROGRESS_STALE_MS = 10 * 60_000;

function num(v: unknown): number {
  const n = typeof v === 'string' ? Number(v) : v;
  return typeof n === 'number' && Number.isFinite(n) ? n : 0;
}

// API 응답(jsonb) → 정규화. 모르는 필드는 버린다.
export function parseProgress(raw: unknown, now = Date.now()): V4Progress {
  const r = (raw && typeof raw === 'object' ? raw : {}) as Record<string, unknown>;
  return {
    activity_day: typeof r.activity_day === 'string' ? r.activity_day : null,
    labeled_today_me: num(r.labeled_today_me),
    labeled_today_all: num(r.labeled_today_all),
    unlabeled_all: num(r.unlabeled_all),
    unlabeled_mine: r.unlabeled_mine === null || r.unlabeled_mine === undefined ? null : num(r.unlabeled_mine),
    fetched_at: now,
  };
}

export function readProgress(): V4Progress | null {
  try {
    const raw = sessionStorage.getItem(KEY);
    if (!raw) return null;
    const p = JSON.parse(raw) as V4Progress;
    return typeof p.fetched_at === 'number' ? p : null;
  } catch {
    return null;
  }
}

export function writeProgress(p: V4Progress): void {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(p));
  } catch {
    // storage 불가 — 표시만 생략.
  }
}

// 확정 1건 반영(순수): 내가 +1, 전체 +1, 남은 -1(내 카메라 영상이면 mine 도 -1). 음수는 0 으로.
export function applyVerdictToProgress(p: V4Progress, inMyCameras: boolean): V4Progress {
  return {
    ...p,
    labeled_today_me: p.labeled_today_me + 1,
    labeled_today_all: p.labeled_today_all + 1,
    unlabeled_all: Math.max(0, p.unlabeled_all - 1),
    unlabeled_mine: p.unlabeled_mine === null ? null : Math.max(0, p.unlabeled_mine - (inMyCameras ? 1 : 0)),
  };
}

export function isProgressStale(p: V4Progress, now = Date.now()): boolean {
  return now - p.fetched_at > PROGRESS_STALE_MS;
}

// 표시 문구(순수). scope 에 따라 "남은" 기준이 다르다.
export function progressLabel(p: V4Progress, scope: 'mine' | 'all'): string {
  const remaining = scope === 'mine' ? p.unlabeled_mine : p.unlabeled_all;
  const rem = remaining === null ? '배정 없음' : `남은 ${remaining}개`;
  return `오늘 내가 ${p.labeled_today_me}개 · ${rem}`;
}
