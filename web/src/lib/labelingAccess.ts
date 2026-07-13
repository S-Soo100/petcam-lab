import 'server-only';

import { NextRequest, NextResponse } from 'next/server';

import { isLabeler, isOwnerId, verifyBearer } from '@/lib/clipPerms';
import { supabaseAdmin } from '@/lib/supabase';
import { databaseUnavailable } from '@/lib/apiErrors';
import { getTutorialAccess, tutorialGateResponse } from '@/lib/labelingTutorialGate';

// 튜토리얼 접근 상태 조회는 gate 모듈이 SOT. access API 가 재사용하도록 re-export.
export { getTutorialAccess } from '@/lib/labelingTutorialGate';

// 라벨링 접근 상태 판정 — 인증(로그인)과 라벨링 권한을 분리한다(§5).
//
// 판정 순서: owner → labelers → application → unregistered (§7).
// 이 순서라서 stale 한 신청 상태가 실제 권한(labelers)을 덮어쓰지 못한다.
// 실제 영상 접근의 SOT 는 labelers 이며, application.status='approved' 단독으로는
// 접근을 허용하지 않는다.

export type AccessStatus =
  | 'owner'
  | 'labeler'
  | 'pending'
  | 'rejected'
  | 'unregistered';

export type ApplicationStatus = 'pending' | 'approved' | 'rejected';

export interface LabelingAccess {
  status: AccessStatus;
  display_name: string | null;
  email: string;
}

// 순수 판정 로직 — DB 결과를 받아 상태 하나로 접는다. 단위 테스트 대상.
export function decideAccessStatus(input: {
  isOwner: boolean;
  isLabeler: boolean;
  applicationStatus: ApplicationStatus | null;
}): AccessStatus {
  if (input.isOwner) return 'owner';
  if (input.isLabeler) return 'labeler';
  if (input.applicationStatus === 'rejected') return 'rejected';
  // pending, 그리고 labelers 에는 없는 stray 'approved'(비정상 상태)도 접근 불가로 본다.
  // SOT 가 labelers 이므로 approved 신청만으로 승격하지 않고 승인 대기로 취급한다.
  if (
    input.applicationStatus === 'pending' ||
    input.applicationStatus === 'approved'
  ) {
    return 'pending';
  }
  return 'unregistered';
}

// 인증된 사용자의 접근 상태 + 표시용 이름/이메일. /api/labeling-access 가 사용.
export async function getLabelingAccess(user: {
  id: string;
  email?: string | null;
  display_name?: string | null;
}): Promise<LabelingAccess> {
  const owner = isOwnerId(user.id);
  const labeler = owner ? false : await isLabeler(user.id);

  const { data, error } = await supabaseAdmin
    .from('labeler_applications')
    .select('status, display_name, email')
    .eq('user_id', user.id)
    .limit(1);
  // 신청 조회 실패는 접근을 넓히면 안 되므로 "신청 없음"으로 보수 처리한다.
  // owner/labeler 는 이미 위에서 확정됐으니 이 실패로 권한이 사라지지 않는다.
  const application = error ? null : (data ?? [])[0] ?? null;

  const status = decideAccessStatus({
    isOwner: owner,
    isLabeler: labeler,
    applicationStatus:
      (application?.status as ApplicationStatus | undefined) ?? null,
  });

  return {
    status,
    display_name:
      (application?.display_name as string | undefined) ??
      user.display_name ??
      null,
    email: user.email ?? (application?.email as string | undefined) ?? '',
  };
}

// ── 라우트 가드 ───────────────────────────────────────────────────

export type OwnerResult =
  | { ok: true; userId: string }
  | { ok: false; response: NextResponse };

// owner(DEV_USER_ID) 전용 API 가드. env 누락이면 503(내부 UUID 미노출, §9).
export async function requireOwner(req: NextRequest): Promise<OwnerResult> {
  const authResult = await verifyBearer(req);
  if (!authResult.ok) return { ok: false, response: authResult.response };
  const { userId } = authResult.auth;

  if (!process.env.DEV_USER_ID) {
    return {
      ok: false,
      response: NextResponse.json(
        { detail: 'owner administration unavailable' },
        { status: 503 },
      ),
    };
  }
  if (!isOwnerId(userId)) {
    return {
      ok: false,
      response: NextResponse.json({ detail: 'forbidden' }, { status: 403 }),
    };
  }
  return { ok: true, userId };
}

export type LabelingAccessResult =
  | { ok: true; userId: string; isOwner: boolean }
  | { ok: false; response: NextResponse };

// 큐·단건·영상 URL·라벨·GT·VLM 검수 공통 가드 — owner 또는 실제 labelers 멤버만(§8).
// 접근 상태 판정(getLabelingAccess)과 달리 여기서는 pending/rejected 를 바로 차단한다.
export async function requireLabelingAccess(
  req: NextRequest,
): Promise<LabelingAccessResult> {
  const authResult = await verifyBearer(req);
  if (!authResult.ok) return { ok: false, response: authResult.response };
  const { userId } = authResult.auth;

  if (isOwnerId(userId)) {
    return { ok: true, userId, isOwner: true };
  }

  // labelers 조회 실패는 502 로 surface (verifyRouterReviewer 와 동일 패턴) —
  // 일시 DB 오류를 조용한 403 으로 오해하지 않게 한다.
  const { data, error } = await supabaseAdmin
    .from('labelers')
    .select('user_id')
    .eq('user_id', userId)
    .limit(1);
  if (error) {
    return {
      ok: false,
      response: databaseUnavailable('labeling access guard', error),
    };
  }
  if ((data ?? []).length === 0) {
    // 승인 대기/거절/미신청 — 큐·영상 접근 불가. 클라이언트는 access 상태로
    // 승인 대기 UI 로 라우팅하며, 이 403 은 직접 API 호출용 backstop 이다.
    return {
      ok: false,
      response: NextResponse.json({ detail: 'forbidden' }, { status: 403 }),
    };
  }
  return { ok: true, userId, isOwner: false };
}

// 본 큐·일반 clip 접근용 가드(설계 §12). requireLabelingAccess(멤버십) 위에
// active 튜토리얼 완료/면제를 얹는다. owner 는 전면 bypass. 미완료 labeler 는
// 403 { detail: 'tutorial_required' } → 클라이언트가 /labeling/tutorial 로 이동.
export async function requireProductionLabelingAccess(
  req: NextRequest,
): Promise<LabelingAccessResult> {
  const base = await requireLabelingAccess(req);
  if (!base.ok) return base;
  if (base.isOwner) return base;
  const blocked = await tutorialGateResponse(base.userId);
  if (blocked) return { ok: false, response: blocked };
  return base;
}
