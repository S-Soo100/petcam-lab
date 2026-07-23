import { NextRequest, NextResponse } from 'next/server';

import { supabaseAdmin } from '@/lib/supabase';
import { currentActivityDay } from '@/lib/motionBlindReview';
import {
  blindDatabaseError,
  blindRpcErrorResponse,
  mapBlindWorkspaceRow,
  requireBlindLabeler,
  type BlindWorkspaceRow,
} from '@/lib/motionBlindReviewServer';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

// GET /api/labeling-v3/blind/workspace — group/header/progress/활동일 목록(설계 §4).
//
// reviewer id 는 bearer access 에서만 온다. 직전 닫힌 활동일(어제) 기준으로 30일 보존창의
// live slot 을 eager materialize 한 뒤(늦은 clip 편입 포함), 집계만 반환한다. 상대 원문 0.
function previousClosedDay(now: Date): string {
  const today = currentActivityDay(now);
  const d = new Date(`${today}T00:00:00.000Z`);
  d.setUTCDate(d.getUTCDate() - 1);
  return d.toISOString().slice(0, 10);
}

export async function GET(req: NextRequest) {
  const access = await requireBlindLabeler(req);
  if (!access.ok) return access.response;
  const { userId } = access;

  const yesterday = previousClosedDay(new Date());

  try {
    // late slot 편입(멱등). id 는 bearer 에서만 — body/query 를 신뢰하지 않는다.
    const ensured = await supabaseAdmin.rpc('fn_ensure_motion_review_slots', {
      p_reviewer_id: userId,
      p_activity_day: yesterday,
    });
    if (ensured.error) return blindRpcErrorResponse(ensured.error) ?? blindDatabaseError(ensured.error);

    const { data, error } = await supabaseAdmin.rpc('fn_get_motion_blind_workspace', {
      p_reviewer_id: userId,
    });
    if (error) return blindRpcErrorResponse(error) ?? blindDatabaseError(error);

    const row = (data ?? [])[0] as BlindWorkspaceRow | undefined;
    if (!row) {
      // 방어: RPC 가 행을 안 주면 미배정 상태로 응답한다.
      return NextResponse.json({
        workspace: mapBlindWorkspaceRow({
          group_id: null,
          group_name: null,
          priority_activity_day: null,
          oldest_unlocked_activity_day: null,
          available_days: null,
          clip_total: 0,
          own_submitted: 0,
          partner_submitted: 0,
          agreed_count: 0,
          conflict_count: 0,
          awaiting_count: 0,
          late_added_count: 0,
          members: null,
        }),
      });
    }
    return NextResponse.json({ workspace: mapBlindWorkspaceRow(row) });
  } catch (cause) {
    return blindDatabaseError(cause);
  }
}
