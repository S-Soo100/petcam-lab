import { NextRequest, NextResponse } from 'next/server';

import { highlightDatabaseError, highlightRpcErrorResponse } from '@/lib/highlightV4Server';
import { requireLabelingAccess } from '@/lib/labelingAccess';
import { readGmeActiveContract } from '@/lib/labelingV3Server';
import { parseV4ListRequest } from '@/lib/labelingV4Server';
import { supabaseAdmin } from '@/lib/supabase';
import { NEXT_CANDIDATES, pickUnclaimed } from '../_claims';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

// GET /api/labeling-v4/continue?scope=mine|all&camera_id=… — "이어서 라벨링"(UX ③) 목적지.
// 현재 scope·카메라 필터의 '라벨 안 된' 영상 후보 몇 개를 받아 남이 보는 중인 것을 건너뛴다(UX ⑤).
export async function GET(req: NextRequest) {
  const access = await requireLabelingAccess(req);
  if (!access.ok) return access.response;
  let parsed;
  try { parsed = parseV4ListRequest(req.nextUrl.searchParams); } catch (e) { return NextResponse.json({ detail: `요청 값이 잘못됐어(${(e as Error).message}).`, code: 'invalid_request' }, { status: 400 }); }
  try {
    const contract = readGmeActiveContract();
    const { data, error } = await supabaseAdmin.rpc('fn_list_labeling_v4_clips', {
      p_viewer_id: access.userId, p_is_owner: access.isOwner, p_scope: parsed.scope, p_camera_ids: parsed.cameraIds,
      p_label_state: 'unlabeled', p_highlight_state: null, p_behavior_flag: null,
      p_engine_schema_version: contract.engine_schema_version, p_algorithm_version: contract.algorithm_version, p_detector_identity: contract.detector_identity,
      p_cursor_started_at: null, p_cursor_id: null, p_limit: NEXT_CANDIDATES,
    });
    if (error) return highlightRpcErrorResponse(error) ?? highlightDatabaseError(error);
    const ids = ((data ?? []) as { clip_id?: unknown }[]).map((r) => r.clip_id).filter((v): v is string => typeof v === 'string');
    return NextResponse.json({ clip_id: await pickUnclaimed(ids, access.userId) });
  } catch (cause) {
    return highlightDatabaseError(cause);
  }
}
