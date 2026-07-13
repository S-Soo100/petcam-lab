import { describe, expect, it } from 'vitest';

import { decideAccessStatus } from './labelingAccess';

describe('decideAccessStatus', () => {
  it('treats DEV_USER_ID owner as owner even with a stale application', () => {
    expect(
      decideAccessStatus({
        isOwner: true,
        isLabeler: false,
        applicationStatus: 'rejected',
      }),
    ).toBe('owner');
  });

  it('treats an actual labelers member as labeler', () => {
    expect(
      decideAccessStatus({
        isOwner: false,
        isLabeler: true,
        applicationStatus: 'pending',
      }),
    ).toBe('labeler');
  });

  it('maps a pending application to pending', () => {
    expect(
      decideAccessStatus({
        isOwner: false,
        isLabeler: false,
        applicationStatus: 'pending',
      }),
    ).toBe('pending');
  });

  it('maps a rejected application to rejected', () => {
    expect(
      decideAccessStatus({
        isOwner: false,
        isLabeler: false,
        applicationStatus: 'rejected',
      }),
    ).toBe('rejected');
  });

  it('denies access to an approved application without a labelers row (SOT = labelers)', () => {
    // 승인 상태만으로는 접근 불가 — labelers 에 없으면 승인 대기로 취급.
    expect(
      decideAccessStatus({
        isOwner: false,
        isLabeler: false,
        applicationStatus: 'approved',
      }),
    ).toBe('pending');
  });

  it('maps no application to unregistered', () => {
    expect(
      decideAccessStatus({
        isOwner: false,
        isLabeler: false,
        applicationStatus: null,
      }),
    ).toBe('unregistered');
  });

  it('never lets a stale application override real labeler membership', () => {
    // 순서 보장: labelers 가 application 보다 우선.
    expect(
      decideAccessStatus({
        isOwner: false,
        isLabeler: true,
        applicationStatus: 'rejected',
      }),
    ).toBe('labeler');
  });
});
