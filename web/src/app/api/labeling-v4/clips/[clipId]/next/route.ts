import { NextRequest, NextResponse } from 'next/server';

import { highlightDatabaseError, highlightRpcErrorResponse } from '@/lib/highlightV4Server';
import { readGmeActiveContract } from '@/lib/labelingV3Server';
import { supabaseAdmin } from '@/lib/supabase';
import { loadV4ClipAccess } from '../../../_access';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

// GET /api/labeling-v4/clips/[clipId]/next — 같은 카메라의 다음 '라벨 안 된' 영상 id.
// keyset cursor 를 현재 clip 의 (started_at, id) 로 서버가 직접 세워 목록 머리로 점프하지 않는다(정렬은
// started_at DESC 라 "다음" = 더 오래된 쪽). 카메라가 없는 clip 은 카메라 필터 없이 전체에서 찾는다.
export async function GET(req: NextRequest, { params }: { params: { clipId: string } }) {
  try {
    const access = await loadV4ClipAccess(req, params.clipId);
    if (!access.ok) return access.response;
    const { clip } = access;
    const contract = readGmeActiveContract();
    const { data, error } = await supabaseAdmin.rpc('fn_list_labeling_v4_clips', {
      p_viewer_id: access.userId, p_is_owner: access.isOwner, p_scope: 'all',
      p_camera_ids: clip.camera_id ? [clip.camera_id] : null,
      p_label_state: 'unlabeled', p_highlight_state: null,
      p_engine_schema_version: contract.engine_schema_version, p_algorithm_version: contract.algorithm_version, p_detector_identity: contract.detector_identity,
      p_cursor_started_at: clip.started_at, p_cursor_id: clip.id, p_limit: 1,
    });
    if (error) return highlightRpcErrorResponse(error) ?? highlightDatabaseError(error);
    const next = ((data ?? []) as { clip_id?: unknown }[])[0];
    return NextResponse.json({ next_clip_id: typeof next?.clip_id === 'string' ? next.clip_id : null });
  } catch (cause) {
    return highlightDatabaseError(cause);
  }
}
