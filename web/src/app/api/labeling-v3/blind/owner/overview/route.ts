import { NextRequest, NextResponse } from 'next/server';

import { supabaseAdmin } from '@/lib/supabase';
import { databaseUnavailable } from '@/lib/apiErrors';
import { requireOwner } from '@/lib/labelingAccess';
import { mapOwnerOverview, parseActivityDay } from '@/lib/labelingRoleServer';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

// GET /api/labeling-v3/blind/owner/overview?activity_day=YYYY-MM-DD — Owner 운영 현황(설계 §7.1).
//
// requireOwner 전용. 기본 활동일 = 직전 닫힌 활동일(07:00 KST 경계). 출력은 집계만이며 reviewer
// UUID·이메일·개별 제출 body 를 포함하지 않는다(매퍼 allowlist).
export async function GET(req: NextRequest) {
  const access = await requireOwner(req);
  if (!access.ok) return access.response;

  const dayResult = parseActivityDay(req.nextUrl.searchParams.get('activity_day'), new Date());
  if (!dayResult.ok) return dayResult.response;

  try {
    const { data, error } = await supabaseAdmin.rpc('fn_get_motion_blind_owner_overview', {
      p_activity_day: dayResult.value,
    });
    if (error) return databaseUnavailable('labeling owner overview', error);
    return NextResponse.json(mapOwnerOverview(data));
  } catch (cause) {
    return databaseUnavailable('labeling owner overview', cause);
  }
}
