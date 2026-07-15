import { NextRequest, NextResponse } from 'next/server';

import { requireOwner } from '@/lib/labelingAccess';
import { supabaseAdmin } from '@/lib/supabase';
import { databaseUnavailable } from '@/lib/apiErrors';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

// GET /api/labeling-triage/cameras — owner-only 격리함 카메라 필터 옵션(설계 §8.1).
// product owner 소유 카메라가 아니라 "실제 triage 대상 카메라"만 준다(테스트 카메라 계정과
// product owner 가 분리돼 있어 /labels/filter-options 를 재사용하지 않는다). RPC 가 DISTINCT.
export async function GET(req: NextRequest) {
  const owner = await requireOwner(req);
  if (!owner.ok) return owner.response;

  try {
    const { data, error } = await supabaseAdmin.rpc('fn_triage_camera_options');
    if (error) throw error;
    const cameras = (data ?? []).map(
      (row: { camera_id: string; name: string | null }) => ({
        camera_id: row.camera_id,
        name: row.name ?? row.camera_id,
      }),
    );
    return NextResponse.json({ cameras });
  } catch (cause) {
    return databaseUnavailable('labeling triage cameras', cause);
  }
}
