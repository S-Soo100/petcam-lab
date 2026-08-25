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
  it('라벨러와 owner 모두 데이터 현황을 본다', () => {
    expect(roleNavItems('labeler').map((x) => x.label)).toEqual([
      '오늘 작업',
      '내 기록',
      '영상 보기',
      '데이터 현황',
      '게코 박스',
      'GME 점검',
    ]);
    expect(roleNavItems('owner').map((x) => x.label)).toEqual([
      '운영 현황',
      '불일치 검수',
      '팀 관리',
      '데이터 현황',
      '게코 연구',
      'GME 점검',
    ]);
  });

  it('GME 점검은 승인 역할 모두에 같은 blind 경로로 보인다', () => {
    for (const role of ['owner', 'labeler'] as const) {
      expect(roleNavItems(role)).toContainEqual({
        href: '/labeling/gme-audit',
        label: 'GME 점검',
        mobileLabel: 'GME',
        activePrefixes: ['/labeling/gme-audit'],
      });
    }
  });

  it('이어짐 확인은 배정된 사용자에게만 추가한다', () => {
    expect(roleNavItems('labeler', false).map((x) => x.label)).not.toContain('이어짐 확인');
    expect(roleNavItems('labeler', true).map((x) => x.label)).toContain('이어짐 확인');
    expect(roleNavItems('owner', true).map((x) => x.label)).toContain('이어짐 확인');
    expect(roleNavItems('unapproved', true)).toEqual([]);
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
