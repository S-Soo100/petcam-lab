import { NextRequest, NextResponse } from 'next/server';

import { supabaseAdmin } from '@/lib/supabase';
import { databaseUnavailable } from '@/lib/apiErrors';
import { requireProductionLabelingAccess } from '@/lib/labelingAccess';
import {
  buildLibraryPage,
  parseLibraryFilters,
  type LibraryRow,
} from '@/lib/labelingRoleServer';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

// GET /api/labeling-v3/library — 공용 읽기 전용 영상 보관함(설계 §5.3·§6).
//
// - owner·승인 라벨러 모두 허용, 미승인은 requireProductionLabelingAccess 가 차단.
// - 모든 카메라를 허용한다(그룹 필터 없음). write control 은 하나도 제공하지 않는다.
// - 확정 전 라벨은 RPC 가 상태만 노출하고 final_decision/final_gt 를 null 로 준다(설계 §6.1).
// - p_owner_id 는 legacy 라벨 출처(기존 Owner vs 기존 단일) 구분용. DEV_USER_ID 누락 시 503.
export async function GET(req: NextRequest) {
  const access = await requireProductionLabelingAccess(req);
  if (!access.ok) return access.response;

  const parsed = parseLibraryFilters(req.nextUrl.searchParams);
  if (!parsed.ok) return parsed.response;
  const filters = parsed.value;

  if (!process.env.DEV_USER_ID) {
    return NextResponse.json({ detail: '라벨 출처를 확인할 수 없어.' }, { status: 503 });
  }

  try {
    const { data, error } = await supabaseAdmin.rpc('fn_list_motion_labeling_library', {
      p_owner_id: process.env.DEV_USER_ID,
      p_clip_id: null,
      ...filters.rpc,
      p_limit: filters.limit + 1,
    });
    if (error) return databaseUnavailable('labeling library', error);
    return NextResponse.json(buildLibraryPage((data ?? []) as LibraryRow[], filters));
  } catch (cause) {
    return databaseUnavailable('labeling library', cause);
  }
}
