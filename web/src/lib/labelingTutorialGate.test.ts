import { describe, expect, it } from 'vitest';

import { decideTutorialAccess } from './labelingTutorialGate';

describe('decideTutorialAccess', () => {
  it('active 없음/불완전 → labeler 는 required unavailable', () => {
    const a = decideTutorialAccess({ activeComplete: false, isOwner: false, progress: null });
    expect(a).toEqual({ required: true, status: 'unavailable', completed_lessons: 0, total_lessons: 5 });
  });

  it('active 없음 → owner 는 required=false (준비 중이어도 차단 안 함)', () => {
    const a = decideTutorialAccess({ activeComplete: false, isOwner: true, progress: null });
    expect(a.required).toBe(false);
    expect(a.status).toBe('unavailable');
  });

  it('progress 없음 → labeler 는 not_started required', () => {
    const a = decideTutorialAccess({ activeComplete: true, isOwner: false, progress: null });
    expect(a).toEqual({ required: true, status: 'not_started', completed_lessons: 0, total_lessons: 5 });
  });

  it('진행 중 labeler → required in_progress, completed_lessons 반영', () => {
    const a = decideTutorialAccess({
      activeComplete: true, isOwner: false,
      progress: { completed: false, waived: false, completedLessons: 3 },
    });
    expect(a).toEqual({ required: true, status: 'in_progress', completed_lessons: 3, total_lessons: 5 });
  });

  it('완료 → required=false completed 5/5', () => {
    const a = decideTutorialAccess({
      activeComplete: true, isOwner: false,
      progress: { completed: true, waived: false, completedLessons: 5 },
    });
    expect(a).toEqual({ required: false, status: 'completed', completed_lessons: 5, total_lessons: 5 });
  });

  it('면제 → required=false waived (미완료여도)', () => {
    const a = decideTutorialAccess({
      activeComplete: true, isOwner: false,
      progress: { completed: false, waived: true, completedLessons: 1 },
    });
    expect(a.required).toBe(false);
    expect(a.status).toBe('waived');
  });

  it('owner 는 active 완비여도 required=false', () => {
    const a = decideTutorialAccess({
      activeComplete: true, isOwner: true,
      progress: { completed: false, waived: false, completedLessons: 0 },
    });
    expect(a.required).toBe(false);
    expect(a.status).toBe('in_progress');
  });
});
