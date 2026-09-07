import { describe, expect, it } from 'vitest';

import { applyVerdictToProgress, isProgressStale, parseProgress, progressLabel } from './labelingV4Progress';

describe('labelingV4Progress', () => {
  it('jsonb 응답을 정규화하고 문자열 숫자·null 을 처리한다', () => {
    const p = parseProgress({ activity_day: '2026-09-08', labeled_today_me: '12', labeled_today_all: 40, unlabeled_all: '300', unlabeled_mine: null, junk: 1 }, 5);
    expect(p).toEqual({ activity_day: '2026-09-08', labeled_today_me: 12, labeled_today_all: 40, unlabeled_all: 300, unlabeled_mine: null, fetched_at: 5 });
    expect(parseProgress(null).unlabeled_all).toBe(0);
  });
  it('확정 1건 반영: 내 카메라면 mine 도 -1, 0 아래로 안 내려감', () => {
    const p = parseProgress({ labeled_today_me: 1, labeled_today_all: 2, unlabeled_all: 1, unlabeled_mine: 0 });
    const next = applyVerdictToProgress(p, true);
    expect(next).toMatchObject({ labeled_today_me: 2, labeled_today_all: 3, unlabeled_all: 0, unlabeled_mine: 0 });
    expect(applyVerdictToProgress(parseProgress({ unlabeled_mine: 5, unlabeled_all: 9 }), false)).toMatchObject({ unlabeled_mine: 5, unlabeled_all: 8 });
  });
  it('표시 문구는 scope 별 남은 기준, 배정 없으면 안내', () => {
    const p = parseProgress({ labeled_today_me: 3, unlabeled_all: 100, unlabeled_mine: 20 });
    expect(progressLabel(p, 'mine')).toBe('오늘 내가 3개 · 남은 20개');
    expect(progressLabel(p, 'all')).toBe('오늘 내가 3개 · 남은 100개');
    expect(progressLabel(parseProgress({ unlabeled_mine: null }), 'mine')).toBe('오늘 내가 0개 · 배정 없음');
  });
  it('10분 지나면 stale', () => {
    const p = parseProgress({}, 0);
    expect(isProgressStale(p, 60_000)).toBe(false);
    expect(isProgressStale(p, 11 * 60_000)).toBe(true);
  });
});
