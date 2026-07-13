import { NextRequest, NextResponse } from 'next/server';

import { isLabeler } from '@/lib/clipPerms';
import { supabaseAdmin } from '@/lib/supabase';
import { databaseUnavailable } from '@/lib/apiErrors';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

// POST /api/labeler-applications
// 로그인된 사용자가 라벨러 참여를 신청한다. body = { display_name }.
//
// 규칙(§7):
// - user_id·email 은 서버(JWT)에서 취득, 브라우저 입력을 신뢰하지 않는다.
// - 이미 labelers 멤버(=승인됨)면 재신청 거부.
// - rejected 는 스스로 되돌리지 않는다(owner 재승인 필요) → 거부.
// - pending 재호출은 이름만 갱신하고 같은 row 를 반환(idempotent).
export async function POST(req: NextRequest) {
  const authHeader = req.headers.get('authorization') || '';
  const token = authHeader.startsWith('Bearer ') ? authHeader.slice(7) : null;
  if (!token) {
    return NextResponse.json({ detail: 'unauthorized' }, { status: 401 });
  }

  const {
    data: { user },
    error: authError,
  } = await supabaseAdmin.auth.getUser(token);
  if (authError || !user) {
    return NextResponse.json({ detail: 'invalid token' }, { status: 401 });
  }

  let displayName: string;
  try {
    const body = await req.json();
    displayName = String(body?.display_name ?? '').trim();
  } catch {
    return NextResponse.json({ detail: '요청 형식이 잘못됐어.' }, { status: 400 });
  }
  if (displayName.length < 1 || displayName.length > 80) {
    return NextResponse.json(
      { detail: '이름은 공백을 제외하고 1~80자여야 해.' },
      { status: 400 },
    );
  }

  try {
    // 이미 라벨러(SOT)면 신청 불필요 — 재신청 거부.
    if (await isLabeler(user.id)) {
      return NextResponse.json(
        { detail: '이미 승인된 라벨러야.' },
        { status: 409 },
      );
    }

    const { data: existingRows, error: selError } = await supabaseAdmin
      .from('labeler_applications')
      .select('*')
      .eq('user_id', user.id)
      .limit(1);
    if (selError) throw new Error(selError.message);
    const existing = (existingRows ?? [])[0];

    if (existing?.status === 'rejected') {
      // 거절된 계정은 스스로 pending 으로 되돌리지 못한다.
      return NextResponse.json(
        { detail: '승인이 거절된 계정이야. 관리자에게 문의해.' },
        { status: 409 },
      );
    }

    const now = new Date().toISOString();

    if (existing) {
      // pending 재호출 — 이름만 갱신하고 상태 유지(idempotent).
      const { data, error } = await supabaseAdmin
        .from('labeler_applications')
        .update({ display_name: displayName, email: user.email ?? existing.email, updated_at: now })
        .eq('user_id', user.id)
        .select('*')
        .single();
      if (error) throw new Error(error.message);
      return NextResponse.json(data, { status: 200 });
    }

    const { data, error } = await supabaseAdmin
      .from('labeler_applications')
      .insert({
        user_id: user.id,
        email: user.email ?? '',
        display_name: displayName,
        status: 'pending',
        requested_at: now,
        updated_at: now,
      })
      .select('*')
      .single();
    if (error) throw new Error(error.message);
    return NextResponse.json(data, { status: 201 });
  } catch (cause) {
    return databaseUnavailable('labeler application', cause);
  }
}
