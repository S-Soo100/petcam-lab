import { NextRequest, NextResponse } from 'next/server';

import { getLabelingAccess, getTutorialAccess } from '@/lib/labelingAccess';
import { supabaseAdmin } from '@/lib/supabase';
import { databaseUnavailable } from '@/lib/apiErrors';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

// GET /api/labeling-access
// 인증된 사용자 누구나 호출 가능 — 로그인 후 어디로 보낼지 클라이언트가 이걸로 결정한다.
// 판정 순서: owner → labelers → application → unregistered (§7).
export async function GET(req: NextRequest) {
  const authHeader = req.headers.get('authorization') || '';
  const token = authHeader.startsWith('Bearer ') ? authHeader.slice(7) : null;
  if (!token) {
    return NextResponse.json({ detail: 'unauthorized' }, { status: 401 });
  }

  // 이메일·display_name 스냅샷이 필요해 userId 만 주는 verifyBearer 대신 getUser 를 직접 쓴다.
  const {
    data: { user },
    error,
  } = await supabaseAdmin.auth.getUser(token);
  if (error || !user) {
    return NextResponse.json({ detail: 'invalid token' }, { status: 401 });
  }

  try {
    const access = await getLabelingAccess({
      id: user.id,
      email: user.email,
      display_name:
        (user.user_metadata?.display_name as string | undefined) ?? null,
    });
    // tutorial 은 access enum 과 별도 축(설계 §11) — 가입 승인(멤버십)과 교육 완료를 분리.
    const tutorial = await getTutorialAccess(user.id, access.status === 'owner');
    return NextResponse.json({ ...access, tutorial });
  } catch (cause) {
    return databaseUnavailable('labeling access', cause);
  }
}
