import { describe, expect, it } from 'vitest';

import { categorize, redirectTarget } from './labelingRouteAccess';

describe('categorize', () => {
  it('/labeling 은 landing — 두 역할이 각자 홈을 렌더', () => {
    expect(categorize('/labeling')).toBe('landing');
  });

  it('영상 보관함·canary 는 공용 읽기 경로(shared)', () => {
    expect(categorize('/labeling/library')).toBe('shared');
    expect(categorize('/labeling/library/clip-1')).toBe('shared');
    // canary 는 일반 /labeling/blind/** 보다 먼저 분류한다(동일 링크, 역할별 렌더).
    expect(categorize('/labeling/blind/canary/c1')).toBe('shared');
    expect(categorize('/labeling/blind/canary/c1/clip-1')).toBe('shared');
  });

  it('내 기록·이중 블라인드 작업은 라벨러 경로', () => {
    expect(categorize('/labeling/me')).toBe('labeler');
    expect(categorize('/labeling/blind/c1')).toBe('labeler');
  });

  it('운영·연구·직접 라벨링 큐는 owner 경로', () => {
    expect(categorize('/labeling/owner')).toBe('owner');
    expect(categorize('/labeling/owner/research')).toBe('owner');
    expect(categorize('/labeling/motion')).toBe('owner');
    expect(categorize('/labeling/motion/clip-1')).toBe('owner');
    expect(categorize('/labeling/router-review')).toBe('owner');
    expect(categorize('/labeling/quarantine')).toBe('owner');
    expect(categorize('/labeling/quarantine/some-clip-id')).toBe('owner');
    expect(categorize('/labeling/legacy')).toBe('owner');
    expect(categorize('/labeling/team')).toBe('owner');
  });

  it('/labeling/<uuid> motion v3 직접 상세는 owner 전용(라벨러 blind 우회 차단, review-fix P0-2)', () => {
    // 미분류 fallthrough 로 landing 이 되면 승인 라벨러가 owner 직접 라벨링 화면(GT·VLM 검수)을
    // URL 로 열 수 있다. canonical UUID 단일 세그먼트는 owner 로 고정한다.
    expect(categorize('/labeling/11111111-1111-4111-8111-111111111111')).toBe('owner');
    expect(categorize('/labeling/ABCDEF01-2345-4678-89AB-CDEF01234567')).toBe('owner');
    // 라벨러가 직접 URL 을 쳐도 라벨러 홈으로 정렬된다.
    expect(redirectTarget(true, 'labeler', categorize('/labeling/11111111-1111-4111-8111-111111111111'), false)).toBe('/labeling');
  });

  it('이중 블라인드 owner 화면(불일치 검수·그룹 배정)은 owner 전용', () => {
    expect(categorize('/labeling/blind/conflicts')).toBe('owner');
    expect(categorize('/labeling/blind/conflicts/clip-1')).toBe('owner');
    expect(categorize('/labeling/blind/groups')).toBe('owner');
  });

  it('공개/신청/대기/튜토리얼 분류 유지', () => {
    expect(categorize('/labeling/login')).toBe('public');
    expect(categorize('/labeling/signup')).toBe('public');
    expect(categorize('/labeling/apply')).toBe('apply');
    expect(categorize('/labeling/pending')).toBe('pending');
    expect(categorize('/labeling/tutorial')).toBe('tutorial');
  });
});

describe('redirectTarget — 역할별 홈 정렬', () => {
  it('owner 는 자신의 경로/공용/랜딩/튜토리얼에 머문다', () => {
    expect(redirectTarget(true, 'owner', 'owner', false)).toBeNull();
    expect(redirectTarget(true, 'owner', 'shared', false)).toBeNull();
    expect(redirectTarget(true, 'owner', 'landing', false)).toBeNull();
    expect(redirectTarget(true, 'owner', 'tutorial', false)).toBeNull();
  });

  it('owner 가 라벨러 전용 경로를 치면 owner 홈으로', () => {
    expect(redirectTarget(true, 'owner', 'labeler', false)).toBe('/labeling/owner');
  });

  it('labeler 는 자신의 경로/공용/랜딩에 머문다', () => {
    expect(redirectTarget(true, 'labeler', 'labeler', false)).toBeNull();
    expect(redirectTarget(true, 'labeler', 'shared', false)).toBeNull();
    expect(redirectTarget(true, 'labeler', 'landing', false)).toBeNull();
  });

  it('labeler 가 owner 전용 경로를 치면 라벨러 홈으로', () => {
    expect(redirectTarget(true, 'labeler', 'owner', false)).toBe('/labeling');
  });

  it('튜토리얼 미완료 labeler 는 업무 경로 대신 튜토리얼로(설계 §8)', () => {
    expect(redirectTarget(true, 'labeler', 'landing', true)).toBe('/labeling/tutorial');
    expect(redirectTarget(true, 'labeler', 'labeler', true)).toBe('/labeling/tutorial');
    expect(redirectTarget(true, 'labeler', 'shared', true)).toBe('/labeling/tutorial');
    expect(redirectTarget(true, 'labeler', 'tutorial', true)).toBeNull();
    expect(redirectTarget(true, 'labeler', 'landing', false)).toBeNull();
  });

  it('pending/rejected 는 대기 화면, unregistered 는 신청 화면(deep-link 매트릭스)', () => {
    // 미승인 사용자는 어떤 업무·공용 경로를 직접 쳐도 참여 화면으로만 정렬된다(설계 §3.3·§10).
    for (const cat of ['owner', 'labeler', 'shared', 'landing', 'tutorial'] as const) {
      expect(redirectTarget(true, 'pending', cat, false)).toBe('/labeling/pending');
      expect(redirectTarget(true, 'rejected', cat, false)).toBe('/labeling/pending');
      expect(redirectTarget(true, 'unregistered', cat, false)).toBe('/labeling/apply');
    }
    expect(redirectTarget(true, 'pending', 'pending', false)).toBeNull();
    expect(redirectTarget(true, 'unregistered', 'apply', false)).toBeNull();
  });

  it('공개 경로는 세션과 무관하게 통과, 그 외 세션 없으면 로그인으로', () => {
    expect(redirectTarget(false, null, 'public', false)).toBeNull();
    expect(redirectTarget(false, null, 'landing', false)).toBe('/labeling/login');
  });
});
