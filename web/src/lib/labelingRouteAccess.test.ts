import { describe, expect, it } from 'vitest';

import { categorize, matchesSegment, redirectTarget } from './labelingRouteAccess';

describe('categorize', () => {
  it('/labeling 은 landing — 두 역할이 각자 홈을 렌더', () => {
    expect(categorize('/labeling')).toBe('landing');
  });

  it('영상 보관함은 공용 읽기 경로(shared)', () => {
    expect(categorize('/labeling/library')).toBe('shared');
    expect(categorize('/labeling/library/clip-1')).toBe('shared');
    expect(categorize('/labeling/dashboard')).toBe('shared');
    // 화면 경로는 두 역할 공용이고 실제 두 사람 제한은 API assignment guard가 담당한다.
    expect(categorize('/labeling/boundary')).toBe('shared');
    // 화면 진입은 공용이지만 실제 item은 assignment API가 다시 제한한다.
    expect(categorize('/labeling/gme-audit')).toBe('shared');
    expect(categorize('/labeling/gme-audit/11111111-1111-4111-8111-111111111111')).toBe('shared');
  });

  it('GME owner 하위 경로는 owner 전용이고 arbitrary suffix는 어느 승인 역할에도 열지 않는다', () => {
    expect(categorize('/labeling/gme-audit/owner')).toBe('owner');
    expect(categorize('/labeling/gme-audit/owner/item-1')).toBe('owner');
    expect(redirectTarget(true, 'owner', categorize('/labeling/gme-audit/owner'))).toBeNull();
    expect(redirectTarget(true, 'labeler', categorize('/labeling/gme-audit/owner'))).toBe('/labeling/mine');

    for (const path of [
      '/labeling/gme-audit/not-a-uuid',
      '/labeling/gme-audit/11111111-1111-4111-8111-111111111111/extra',
    ]) {
      expect(categorize(path)).toBe('invalid');
      expect(redirectTarget(true, 'owner', categorize(path))).toBe('/labeling/owner');
      expect(redirectTarget(true, 'labeler', categorize(path))).toBe('/labeling/mine');
    }
  });

  it('v4 목록·상세는 승인 역할 공용(shared)', () => {
    expect(categorize('/labeling/mine')).toBe('shared');
    expect(categorize('/labeling/all')).toBe('shared');
    expect(categorize('/labeling/v4/11111111-1111-4111-8111-111111111111')).toBe('shared');
    expect(categorize('/labeling/v4/not-uuid')).toBe('invalid');
  });

  it('퇴역한 이중 blind·내 기록·튜토리얼 경로는 invalid 로 역할 홈으로 보낸다', () => {
    expect(categorize('/labeling/blind')).toBe('invalid');
    expect(categorize('/labeling/blind/c1')).toBe('invalid');
    expect(categorize('/labeling/blind/conflicts')).toBe('invalid');
    expect(categorize('/labeling/blind/canary/c1')).toBe('invalid');
    expect(categorize('/labeling/me')).toBe('invalid');
    expect(categorize('/labeling/me/x')).toBe('invalid');
    // 대화형 튜토리얼은 2026-09-07 owner 결정으로 퇴역 — 화면·API 삭제, URL 은 역할 홈으로.
    expect(categorize('/labeling/tutorial')).toBe('invalid');
    expect(categorize('/labeling/tutorial/3')).toBe('invalid');
    expect(redirectTarget(true, 'owner', categorize('/labeling/tutorial'))).toBe('/labeling/owner');
    expect(redirectTarget(true, 'labeler', categorize('/labeling/tutorial/3'))).toBe('/labeling/mine');
    expect(redirectTarget(true, 'owner', categorize('/labeling/blind/conflicts'))).toBe('/labeling/owner');
    expect(redirectTarget(true, 'labeler', categorize('/labeling/blind/c1'))).toBe('/labeling/mine');
  });

  it('퇴역 prefix 는 세그먼트 경계로만 — /labeling/members·/labeling/mine/* 를 삼키지 않는다', () => {
    expect(categorize('/labeling/members')).toBe('landing');
    expect(categorize('/labeling/mine/anything')).not.toBe('invalid');
    expect(categorize('/labeling/blindfold')).not.toBe('invalid');
    expect(categorize('/labeling/tutorials')).not.toBe('invalid');
    expect(matchesSegment('/labeling/me', '/labeling/me')).toBe(true);
    expect(matchesSegment('/labeling/me/x', '/labeling/me')).toBe(true);
    expect(matchesSegment('/labeling/members', '/labeling/me')).toBe(false);
    expect(matchesSegment('/labeling/mex', '/labeling/me')).toBe(false);
  });

  it('게코 박스는 라벨러 경로', () => {
    expect(categorize('/labeling/yolo')).toBe('labeler');
  });

  it('운영·연구·직접 라벨링 큐는 owner 경로', () => {
    expect(categorize('/labeling/owner')).toBe('owner');
    expect(categorize('/labeling/owner/research')).toBe('owner');
    expect(categorize('/labeling/owner/yolo')).toBe('owner');
    expect(categorize('/labeling/motion')).toBe('owner');
    expect(categorize('/labeling/motion/clip-1')).toBe('owner');
    expect(categorize('/labeling/motion/auto-excluded')).toBe('owner');
    expect(categorize('/labeling/router-review')).toBe('owner');
    expect(categorize('/labeling/quarantine')).toBe('owner');
    expect(categorize('/labeling/quarantine/some-clip-id')).toBe('owner');
    expect(categorize('/labeling/legacy')).toBe('owner');
    expect(categorize('/labeling/team')).toBe('owner');
    expect(categorize('/labeling/boundary/conflicts')).toBe('owner');
  });

  it('/labeling/motion/<uuid> 행동 GT 상세는 승인 역할 공용(2026-09-08 라벨러 개방)', () => {
    expect(categorize('/labeling/motion/11111111-1111-4111-8111-111111111111')).toBe('shared');
    expect(redirectTarget(true, 'labeler', categorize('/labeling/motion/11111111-1111-4111-8111-111111111111'))).toBeNull();
  });

  it('/labeling/<uuid> motion v3 직접 상세는 owner 전용(라벨러 blind 우회 차단, review-fix P0-2)', () => {
    // 미분류 fallthrough 로 landing 이 되면 승인 라벨러가 owner 직접 라벨링 화면(GT·VLM 검수)을
    // URL 로 열 수 있다. canonical UUID 단일 세그먼트는 owner 로 고정한다.
    expect(categorize('/labeling/11111111-1111-4111-8111-111111111111')).toBe('owner');
    expect(categorize('/labeling/ABCDEF01-2345-4678-89AB-CDEF01234567')).toBe('owner');
    // 라벨러가 직접 URL 을 쳐도 라벨러 홈으로 정렬된다.
    expect(redirectTarget(true, 'labeler', categorize('/labeling/11111111-1111-4111-8111-111111111111'))).toBe('/labeling/mine');
  });

  it('공개/신청/대기 분류 유지', () => {
    expect(categorize('/labeling/login')).toBe('public');
    expect(categorize('/labeling/signup')).toBe('public');
    expect(categorize('/labeling/apply')).toBe('apply');
    expect(categorize('/labeling/pending')).toBe('pending');
  });
});

describe('redirectTarget — 역할별 홈 정렬', () => {
  it('owner 는 자신의 경로/공용/랜딩에 머문다', () => {
    expect(redirectTarget(true, 'owner', 'owner')).toBeNull();
    expect(redirectTarget(true, 'owner', 'shared')).toBeNull();
    expect(redirectTarget(true, 'owner', 'landing')).toBeNull();
  });

  it('owner 가 라벨러 전용 경로를 치면 owner 홈으로', () => {
    expect(redirectTarget(true, 'owner', 'labeler')).toBe('/labeling/owner');
  });

  it('labeler 는 자신의 경로/공용/랜딩에 머문다', () => {
    expect(redirectTarget(true, 'labeler', 'labeler')).toBeNull();
    expect(redirectTarget(true, 'labeler', 'shared')).toBeNull();
    expect(redirectTarget(true, 'labeler', 'landing')).toBeNull();
  });

  it('labeler 가 owner 전용 경로를 치면 라벨러 홈(/labeling/mine)으로', () => {
    expect(redirectTarget(true, 'labeler', 'owner')).toBe('/labeling/mine');
  });

  it('pending/rejected 는 대기 화면, unregistered 는 신청 화면(deep-link 매트릭스)', () => {
    // 미승인 사용자는 어떤 업무·공용 경로를 직접 쳐도 참여 화면으로만 정렬된다(설계 §3.3·§10).
    for (const cat of ['owner', 'labeler', 'shared', 'landing', 'invalid'] as const) {
      expect(redirectTarget(true, 'pending', cat)).toBe('/labeling/pending');
      expect(redirectTarget(true, 'rejected', cat)).toBe('/labeling/pending');
      expect(redirectTarget(true, 'unregistered', cat)).toBe('/labeling/apply');
    }
    expect(redirectTarget(true, 'pending', 'pending')).toBeNull();
    expect(redirectTarget(true, 'unregistered', 'apply')).toBeNull();
  });

  it('공개 경로는 세션과 무관하게 통과, 그 외 세션 없으면 로그인으로', () => {
    expect(redirectTarget(false, null, 'public')).toBeNull();
    expect(redirectTarget(false, null, 'landing')).toBe('/labeling/login');
  });
});
