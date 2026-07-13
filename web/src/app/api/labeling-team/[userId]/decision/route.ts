import { NextRequest, NextResponse } from 'next/server';

import { requireOwner } from '@/lib/labelingAccess';
import { supabaseAdmin } from '@/lib/supabase';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const DECISIONS = ['approve', 'reject', 'deactivate'] as const;
type Decision = (typeof DECISIONS)[number];

// POST /api/labeling-team/[userId]/decision  body = { decision }
// owner 전용. 승인/거절/권한 해제를 DB RPC(fn_review_labeler_application)로 원자 처리한다.
// approve → labelers upsert + status=approved. reject/deactivate → labelers delete + status=rejected.
export async function POST(
  req: NextRequest,
  { params }: { params: { userId: string } },
) {
  const owner = await requireOwner(req);
  if (!owner.ok) return owner.response;

  let decision: Decision;
  try {
    const body = await req.json();
    decision = body?.decision;
  } catch {
    return NextResponse.json({ detail: '요청 형식이 잘못됐어.' }, { status: 400 });
  }
  if (!DECISIONS.includes(decision)) {
    return NextResponse.json(
      { detail: `잘못된 decision: ${decision}` },
      { status: 400 },
    );
  }

  const targetUserId = params.userId;
  if (!targetUserId) {
    return NextResponse.json({ detail: 'user id 누락' }, { status: 400 });
  }
  // owner 자신에 대한 처리는 UI·API 모두 거부(§4.5, §7). RPC 도 재차 막지만 여기서 먼저 400.
  if (targetUserId === owner.userId) {
    return NextResponse.json(
      { detail: 'owner 자신의 권한은 변경할 수 없어.' },
      { status: 400 },
    );
  }

  const { data, error } = await supabaseAdmin.rpc(
    'fn_review_labeler_application',
    {
      p_user_id: targetUserId,
      p_reviewer_id: owner.userId,
      p_decision: decision,
    },
  );
  if (error) {
    // RPC 예외 매핑: P0002=신청 없음(404), 22023=잘못된 인자(400), 그 외 502.
    if (error.code === 'P0002') {
      return NextResponse.json({ detail: '신청을 찾을 수 없어.' }, { status: 404 });
    }
    if (error.code === '22023') {
      return NextResponse.json({ detail: error.message }, { status: 400 });
    }
    return NextResponse.json(
      { detail: `supabase error: ${error.message}` },
      { status: 502 },
    );
  }

  // 함수는 갱신된 labeler_applications row 를 반환한다.
  const application = Array.isArray(data) ? data[0] : data;
  return NextResponse.json({ application });
}
