import { describe, expect, it } from 'vitest';

import { categorize, redirectTarget } from './labelingRouteAccess';

describe('categorize', () => {
  it('격리함은 owner 카테고리(팀원 관리와 동급)', () => {
    expect(categorize('/labeling/quarantine')).toBe('owner');
    expect(categorize('/labeling/quarantine/some-clip-id')).toBe('owner');
    expect(categorize('/labeling/team')).toBe('owner');
  });

  it('일반 라벨링 경로는 work', () => {
    expect(categorize('/labeling')).toBe('work');
    expect(categorize('/labeling/me')).toBe('work');
    expect(categorize('/labeling/router-review')).toBe('work');
  });

  it('공개/신청/대기/튜토리얼 분류 유지', () => {
    expect(categorize('/labeling/login')).toBe('public');
    expect(categorize('/labeling/apply')).toBe('apply');
    expect(categorize('/labeling/pending')).toBe('pending');
    expect(categorize('/labeling/tutorial')).toBe('tutorial');
  });
});

describe('redirectTarget — 격리함 접근', () => {
  it('owner 는 격리함에 머문다', () => {
    expect(redirectTarget(true, 'owner', 'owner', false)).toBeNull();
  });

  it('labeler 가 격리함 URL 을 직접 치면 /labeling 으로 튕긴다', () => {
    expect(redirectTarget(true, 'labeler', 'owner', false)).toBe('/labeling');
  });

  it('pending/rejected 는 대기 화면, unregistered 는 신청 화면', () => {
    expect(redirectTarget(true, 'pending', 'owner', false)).toBe('/labeling/pending');
    expect(redirectTarget(true, 'rejected', 'owner', false)).toBe('/labeling/pending');
    expect(redirectTarget(true, 'unregistered', 'owner', false)).toBe('/labeling/apply');
  });

  it('세션 없으면 로그인으로', () => {
    expect(redirectTarget(false, null, 'owner', false)).toBe('/labeling/login');
  });

  it('기존 work 라벨러 흐름 회귀 — 튜토리얼 미완료면 튜토리얼로', () => {
    expect(redirectTarget(true, 'labeler', 'work', true)).toBe('/labeling/tutorial');
    expect(redirectTarget(true, 'labeler', 'work', false)).toBeNull();
  });
});
