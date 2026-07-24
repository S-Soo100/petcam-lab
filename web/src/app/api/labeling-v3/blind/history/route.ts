import { NextRequest, NextResponse } from 'next/server';

import { supabaseAdmin } from '@/lib/supabase';
import { databaseUnavailable } from '@/lib/apiErrors';
import { requireBlindLabeler } from '@/lib/motionBlindReviewServer';
import {
  buildHistoryPage,
  parseHistoryFilters,
  type HistoryRow,
} from '@/lib/labelingRoleServer';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

// GET /api/labeling-v3/blind/history — 라벨러 본인 immutable 제출 기록(설계 §5.2).
//
// - reviewer id 는 항상 bearer access 에서만(body/query 신뢰 X). owner 는 개인 기록 대상이 아니라
//   requireBlindLabeler 가 403 으로 막는다(직접 라벨링 기록은 Owner 홈에서 별도).
// - 상대 제출·digest·reviewer UUID 는 애초에 RPC/매퍼에 없다. final_status 는 확정됨/검수 중뿐.
export async function GET(req: NextRequest) {
  const access = await requireBlindLabeler(req);
  if (!access.ok) return access.response;

  const parsed = parseHistoryFilters(req.nextUrl.searchParams);
  if (!parsed.ok) return parsed.response;
  const filters = parsed.value;

  try {
    const { data, error } = await supabaseAdmin.rpc('fn_list_motion_blind_history', {
      p_reviewer_id: access.userId,
      ...filters.rpc,
      p_limit: filters.limit + 1,
    });
    if (error) return databaseUnavailable('labeling blind history', error);
    return NextResponse.json(buildHistoryPage((data ?? []) as HistoryRow[], filters));
  } catch (cause) {
    return databaseUnavailable('labeling blind history', cause);
  }
}
