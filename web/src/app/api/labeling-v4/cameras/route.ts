import { NextRequest, NextResponse } from 'next/server';

import { highlightDatabaseError } from '@/lib/highlightV4Server';
import { requireLabelingAccess } from '@/lib/labelingAccess';
import { supabaseAdmin } from '@/lib/supabase';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

// GET /api/labeling-v4/cameras — 카메라 옵션 + 내 배정 플래그(필터용).
export async function GET(req: NextRequest) {
  const access = await requireLabelingAccess(req);
  if (!access.ok) return access.response;
  try {
    const { data, error } = await supabaseAdmin.rpc('fn_list_labeling_v4_cameras', { p_viewer_id: access.userId });
    if (error) throw error;
    const cameras = ((data ?? []) as { camera_id: string; camera_name: string; assigned: boolean }[])
      .map((r) => ({ id: r.camera_id, name: r.camera_name, assigned: Boolean(r.assigned) }));
    return NextResponse.json({ cameras });
  } catch (cause) {
    return highlightDatabaseError(cause);
  }
}
