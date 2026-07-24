import { afterAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

// requireOwner 는 bearer 검증 + DEV_USER_ID env 비교만으로 판정한다. labelers/tutorial DB 를
// 절대 조회하지 않음을 증명하려면 supabaseAdmin.from 스파이가 한 번도 호출되지 않아야 한다.
const { verifyBearer, isOwnerId, isLabeler, from } = vi.hoisted(() => ({
  verifyBearer: vi.fn(),
  isOwnerId: vi.fn(),
  isLabeler: vi.fn(),
  from: vi.fn(),
}));
vi.mock('@/lib/clipPerms', () => ({ verifyBearer, isOwnerId, isLabeler }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { from } }));

import { decideAccessStatus, requireOwner } from './labelingAccess';

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

// review-fix P0-2 후속: motion v3 owner-only 가드가 requireOwner 로 통일됐다. 핵심 계약 =
// 라벨러/미승인 요청을 labelers·tutorial DB 조회 없이(supabaseAdmin.from 0회) 거부한다.
describe('requireOwner — Owner 전용 가드 (DB 조회 없이 판정)', () => {
  const OWNER = '00000000-0000-4000-8000-000000000001';
  const PREV = process.env.DEV_USER_ID;

  function req() {
    return new NextRequest('https://label.tera-ai.uk/api/labeling-v3/x');
  }

  beforeEach(() => {
    vi.clearAllMocks();
    process.env.DEV_USER_ID = OWNER;
    verifyBearer.mockResolvedValue({ ok: true, auth: { userId: OWNER } });
    isOwnerId.mockReturnValue(true);
  });
  afterAll(() => {
    process.env.DEV_USER_ID = PREV;
  });

  it('owner 는 통과하고 labelers/tutorial DB 조회 0', async () => {
    const res = await requireOwner(req());
    expect(res).toEqual({ ok: true, userId: OWNER });
    expect(from).not.toHaveBeenCalled();
  });

  it('라벨러(비-owner)는 403 이고 labelers/tutorial DB 조회 0', async () => {
    verifyBearer.mockResolvedValue({ ok: true, auth: { userId: 'labeler-1' } });
    isOwnerId.mockReturnValue(false);
    const res = await requireOwner(req());
    expect(res.ok).toBe(false);
    if (!res.ok) expect(res.response.status).toBe(403);
    expect(from).not.toHaveBeenCalled();
  });

  it('DEV_USER_ID 누락은 503 이고 DB 조회 0', async () => {
    delete process.env.DEV_USER_ID;
    const res = await requireOwner(req());
    expect(res.ok).toBe(false);
    if (!res.ok) expect(res.response.status).toBe(503);
    expect(from).not.toHaveBeenCalled();
  });

  it('인증 실패는 verifyBearer 응답을 그대로 반환하고 DB 조회 0', async () => {
    verifyBearer.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: 'unauthorized' }, { status: 401 }),
    });
    const res = await requireOwner(req());
    expect(res.ok).toBe(false);
    if (!res.ok) expect(res.response.status).toBe(401);
    expect(from).not.toHaveBeenCalled();
  });
});
