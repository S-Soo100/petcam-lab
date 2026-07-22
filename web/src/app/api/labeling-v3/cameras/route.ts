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

function toCameraOption(row: CameraRow) {
  return { id: row.id, name: row.name ?? row.id };
}

// triage label row 의 embed motion_clips 에서 camera_id 를 추출(to-one/배열 모두 방어).
function pickCameraId(row: {
  motion_clips?: { camera_id?: string | null } | { camera_id?: string | null }[] | null;
}): string | null {
  const mc = row.motion_clips;
  if (Array.isArray(mc)) return mc[0]?.camera_id ?? null;
  return mc?.camera_id ?? null;
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

    // labeler: label 상태 clip 의 카메라만. triage.clip_id → motion_clips embed 로 camera 추출.
    const { data: labelRows, error: labelErr } = await supabaseAdmin
      .from('motion_clip_labeling_triage')
      .select('motion_clips!inner(camera_id)')
      .eq('owner_decision', 'label');
    if (labelErr) throw labelErr;

    const cameraIds = Array.from(
      new Set(
        (labelRows ?? [])
          .map((row) => pickCameraId(row as Parameters<typeof pickCameraId>[0]))
          .filter((id): id is string => Boolean(id)),
      ),
    );
    if (cameraIds.length === 0) return NextResponse.json({ cameras: [] });

    const { data, error } = await supabaseAdmin
      .from('cameras')
      .select('id, name')
      .in('id', cameraIds)
      .order('name', { ascending: true });
    if (error) throw error;
    return NextResponse.json({ cameras: (data ?? []).map(toCameraOption) });
  } catch (cause) {
    return motionLabelingDatabaseError(cause);
  }
}
