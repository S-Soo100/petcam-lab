import { NextRequest, NextResponse } from 'next/server';

import { highlightDatabaseError, highlightRpcErrorResponse } from '@/lib/highlightV4Server';
import { readGmeActiveContract } from '@/lib/labelingV3Server';
import { isEvalSampleId } from '@/lib/labelingV4';
import { supabaseAdmin } from '@/lib/supabase';
import { loadV4ClipAccess } from '../../../_access';
import { NEXT_CANDIDATES, pickUnclaimed } from '../../../_claims';

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
    // ?sample=<id> 면 표본 안에서만 다음을 찾는다(2.6.1 준비). 형식이 틀리면 400.
    const sampleRaw = req.nextUrl.searchParams.get('sample');
    if (sampleRaw !== null && !isEvalSampleId(sampleRaw)) {
      return NextResponse.json({ detail: 'sample 값이 잘못됐어.', code: 'invalid_request' }, { status: 400 });
    }
    const contract = readGmeActiveContract();
    const { data, error } = await supabaseAdmin.rpc('fn_list_labeling_v4_clips', {
      p_viewer_id: access.userId, p_is_owner: access.isOwner, p_scope: 'all',
      p_camera_ids: clip.camera_id ? [clip.camera_id] : null,
      p_label_state: 'unlabeled', p_highlight_state: null, p_behavior_flag: null, ...(sampleRaw ? { p_sample_id: sampleRaw } : {}),
      p_engine_schema_version: contract.engine_schema_version, p_algorithm_version: contract.algorithm_version, p_detector_identity: contract.detector_identity,
      p_cursor_started_at: clip.started_at, p_cursor_id: clip.id, p_limit: NEXT_CANDIDATES,
    });
    if (error) return highlightRpcErrorResponse(error) ?? highlightDatabaseError(error);
    // 후보 중 남이 최근(120초)에 연 clip 은 건너뛴다(UX ⑤). 전부 겹치면 첫 후보.
    const ids = ((data ?? []) as { clip_id?: unknown }[]).map((r) => r.clip_id).filter((v): v is string => typeof v === 'string');
    return NextResponse.json({ next_clip_id: await pickUnclaimed(ids, access.userId) });
  } catch (cause) {
    return highlightDatabaseError(cause);
  }
}
