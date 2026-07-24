import { describe, expect, it } from 'vitest';

import {
  resolveLabelingRole,
  roleHome,
  roleNavItems,
} from './labelingRoleNavigation';

describe('resolveLabelingRole', () => {
  it('owner/labeler 는 그대로, 그 외는 미승인', () => {
    expect(resolveLabelingRole('owner')).toBe('owner');
    expect(resolveLabelingRole('labeler')).toBe('labeler');
    expect(resolveLabelingRole('pending')).toBe('unapproved');
    expect(resolveLabelingRole('rejected')).toBe('unapproved');
    expect(resolveLabelingRole('unregistered')).toBe('unapproved');
    expect(resolveLabelingRole(null)).toBe('unapproved');
  });
});

describe('roleNavItems', () => {
  it('라벨러 메뉴는 정확히 세 개', () => {
    expect(roleNavItems('labeler').map((x) => x.label)).toEqual([
      '오늘 작업',
      '내 기록',
      '영상 보기',
    ]);
  });

  it('owner 메뉴는 정확히 세 개', () => {
    expect(roleNavItems('owner').map((x) => x.label)).toEqual([
      '운영 현황',
      '불일치 검수',
      '팀 관리',
    ]);
  });

  it('미승인은 업무 메뉴 없음', () => {
    expect(roleNavItems('unapproved')).toEqual([]);
  });
});

describe('roleHome', () => {
  it('역할별 홈 경로', () => {
    expect(roleHome('owner')).toBe('/labeling/owner');
    expect(roleHome('labeler')).toBe('/labeling');
    expect(roleHome('unapproved')).toBe('/labeling/pending');
  });
});
