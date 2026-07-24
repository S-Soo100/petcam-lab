import { NextRequest, NextResponse } from 'next/server';

import { supabaseAdmin } from '@/lib/supabase';
import { databaseUnavailable } from '@/lib/apiErrors';
import { requireProductionLabelingAccess } from '@/lib/labelingAccess';
import { isValidUuid } from '@/lib/motionBlindReviewServer';
import { mapLibraryRow, type LibraryRow } from '@/lib/labelingRoleServer';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

// GET /api/labeling-v3/library/[clipId] — 공용 읽기 전용 영상 단건(설계 §5.3).
//
// 목록과 같은 read RPC 를 p_clip_id 로 좁혀 호출해 동일한 라벨 공개 계약(확정 전 은닉)을 재사용한다.
// 재생 불가(r2_key 없음)나 미존재 clip 은 RPC 가 행을 주지 않으므로 404.
export async function GET(req: NextRequest, { params }: { params: { clipId: string } }) {
  const access = await requireProductionLabelingAccess(req);
  if (!access.ok) return access.response;

  if (!isValidUuid(params.clipId)) {
    return NextResponse.json({ detail: '잘못된 clip id', code: 'invalid_request' }, { status: 400 });
  }

  if (!process.env.DEV_USER_ID) {
    return NextResponse.json({ detail: '라벨 출처를 확인할 수 없어.' }, { status: 503 });
  }

  try {
    const { data, error } = await supabaseAdmin.rpc('fn_list_motion_labeling_library', {
      p_owner_id: process.env.DEV_USER_ID,
      p_clip_id: params.clipId,
      p_label_state: null,
      p_camera_ids: null,
      p_date_from: null,
      p_date_to: null,
      p_time_from: null,
      p_time_to: null,
      p_label_source: null,
      p_cursor_started_at: null,
      p_cursor_id: null,
      p_limit: 1,
    });
    if (error) return databaseUnavailable('labeling library clip', error);
    const row = ((data ?? []) as LibraryRow[])[0];
    if (!row) {
      return NextResponse.json({ detail: '영상을 찾을 수 없어.', code: 'not_found' }, { status: 404 });
    }
    return NextResponse.json(mapLibraryRow(row));
  } catch (cause) {
    return databaseUnavailable('labeling library clip', cause);
  }
}
