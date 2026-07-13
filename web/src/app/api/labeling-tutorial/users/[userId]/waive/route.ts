import { NextRequest, NextResponse } from 'next/server';

import { requireOwner } from '@/lib/labelingAccess';
import { supabaseAdmin } from '@/lib/supabase';
import { databaseUnavailable } from '@/lib/apiErrors';
import { loadActiveSetId } from '../../../_helpers';

export const runtime = 'nodejs';

// POST /api/labeling-tutorial/users/[userId]/waive — owner 전용(설계 §5.8·§11).
// 완료 면제. 사유 1~200자 필수. waived_at/by/reason audit 보존.
export async function POST(
  req: NextRequest,
  { params }: { params: { userId: string } },
) {
  const owner = await requireOwner(req);
  if (!owner.ok) return owner.response;
  if (!params.userId) {
    return NextResponse.json({ detail: 'user id missing' }, { status: 400 });
  }

  let reason: string;
  try {
    const body = (await req.json()) as { reason?: unknown };
    reason = typeof body.reason === 'string' ? body.reason.trim() : '';
  } catch {
    return NextResponse.json({ detail: '요청 형식이 잘못됐어.' }, { status: 400 });
  }
  if (reason.length < 1 || reason.length > 200) {
    return NextResponse.json({ detail: '면제 사유는 1~200자여야 해.' }, { status: 400 });
  }

  try {
    const setId = await loadActiveSetId();
    if (!setId) {
      return NextResponse.json({ detail: 'tutorial_unavailable' }, { status: 409 });
    }
    const { data, error } = await supabaseAdmin.rpc('fn_waive_tutorial', {
      p_set_id: setId,
      p_user_id: params.userId,
      p_owner_id: owner.userId,
      p_reason: reason,
    });
    if (error) throw new Error(error.message);
    return NextResponse.json({ progress: data });
  } catch (cause) {
    return databaseUnavailable('labeling tutorial waive', cause);
  }
}
