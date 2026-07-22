import { NextRequest, NextResponse } from 'next/server';

import { requireProductionLabelingAccess } from '@/lib/labelingAccess';
import { motionLabelingDatabaseError } from '@/lib/labelingV3Server';
import { supabaseAdmin } from '@/lib/supabase';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

// GET /api/labeling-v3/cameras — 역할별 카메라 필터 옵션(설계 §10).
//
// owner: production cameras 전체(테스트 계정 분리라 소유 필터 없음).
// labeler: 현재 label 큐에 존재하는 카메라만. legacy /labels/filter-options 를 재사용하지 않는다.

interface CameraRow {
  id: string;
  name: string | null;
}

interface LabelerCameraRow {
  camera_id: string;
  camera_name: string | null;
}

function toCameraOption(row: CameraRow) {
  return { id: row.id, name: row.name ?? row.id };
}

export async function GET(req: NextRequest) {
  const access = await requireProductionLabelingAccess(req);
  if (!access.ok) return access.response;

  try {
    if (access.isOwner) {
      const { data, error } = await supabaseAdmin
        .from('cameras')
        .select('id, name')
        .order('name', { ascending: true });
      if (error) throw error;
      return NextResponse.json({ cameras: (data ?? []).map(toCameraOption) });
    }

    // labeler: DB가 실제 처리 가능 조건과 DISTINCT를 함께 적용해 1000행 truncation을 피한다.
    const { data, error } = await supabaseAdmin.rpc(
      'fn_list_motion_clip_labeling_camera_options',
      { p_reviewer_id: access.userId },
    );
    if (error) throw error;
    const cameras = ((data ?? []) as LabelerCameraRow[]).map((row) =>
      toCameraOption({ id: row.camera_id, name: row.camera_name }),
    );
    return NextResponse.json({ cameras });
  } catch (cause) {
    return motionLabelingDatabaseError(cause);
  }
}
