import { NextRequest, NextResponse } from 'next/server';

import { requireOwner } from '@/lib/labelingAccess';
import { supabaseAdmin } from '@/lib/supabase';
import { databaseUnavailable } from '@/lib/apiErrors';
import { loadActiveSetId } from '../../../_helpers';

export const runtime = 'nodejs';

// POST /api/labeling-tutorial/users/[userId]/reset — owner 전용(설계 §11).
// run 번호만 +1, 기존 attempt 는 삭제하지 않고 read-only history 로 보존(설계 §13).
export async function POST(
  req: NextRequest,
  { params }: { params: { userId: string } },
) {
  const owner = await requireOwner(req);
  if (!owner.ok) return owner.response;
  if (!params.userId) {
    return NextResponse.json({ detail: 'user id missing' }, { status: 400 });
  }

  try {
    const setId = await loadActiveSetId();
    if (!setId) {
      return NextResponse.json({ detail: 'tutorial_unavailable' }, { status: 409 });
    }
    const { data, error } = await supabaseAdmin.rpc('fn_reset_tutorial', {
      p_set_id: setId,
      p_user_id: params.userId,
      p_owner_id: owner.userId,
    });
    if (error) throw new Error(error.message);
    return NextResponse.json({ progress: data });
  } catch (cause) {
    return databaseUnavailable('labeling tutorial reset', cause);
  }
}
