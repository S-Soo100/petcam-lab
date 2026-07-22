import { NextRequest, NextResponse } from 'next/server';

import { requireProductionLabelingAccess } from '@/lib/labelingAccess';
import { parseMotionQueueRequest } from '@/lib/labelingV3QueueServer';
import {
  motionLabelingDatabaseError,
  motionRpcErrorResponse,
} from '@/lib/labelingV3Server';
import { supabaseAdmin } from '@/lib/supabase';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

// GET /api/labeling-v3/[clipId]/next — owner 전용 "현재 필터의 다음 미분류 영상"(설계 §6).
//
// 연속 검수: owner 가 결과를 확인한 뒤 현재 필터에서 현재 영상보다 바로 이전 순서의 미분류 영상으로
// 넘어간다. labeler 는 기존 큐 흐름을 유지하므로 owner 만 호출한다(그 외 403). 새 migration/RPC 없이
// 기존 fn_list_motion_clip_labeling_queue 를 p_state='unreviewed', cursor=(현재 started_at, 현재 id),
// p_limit=1 로 재사용한다. 정렬 (started_at DESC, id DESC) 를 그대로 써서 같은 timestamp 도 id
// tie-break 로 중복·누락 없이 다음 위치를 찾는다. 다른 사용자가 이미 처리한 영상은 unreviewed 조건에서
// 자연히 빠진다. 필터 검증은 queue route 와 같은 parser(labelingV3QueueServer)를 공유한다.

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function badRequest(detail: string) {
  return NextResponse.json({ detail, code: 'invalid_request' }, { status: 400 });
}

export async function GET(req: NextRequest, { params }: { params: { clipId: string } }) {
  const access = await requireProductionLabelingAccess(req);
  if (!access.ok) return access.response;
  // owner 전용. labeler 는 DB 접근 전에 403 으로 막는다.
  if (!access.isOwner) {
    return NextResponse.json({ detail: 'forbidden' }, { status: 403 });
  }

  const clipId = params.clipId;
  if (!UUID.test(clipId)) return badRequest('잘못된 clip id');

  // state 는 무시하고 항상 unreviewed 를 강제하지만, camera/date/media/limit 검증은 큐와 동일하게 한다.
  const parsed = parseMotionQueueRequest(req.nextUrl.searchParams, true);
  if ('error' in parsed) return badRequest(parsed.error);

  try {
    // 현재 clip 의 started_at 을 서버에서 다시 읽는다(클라이언트 cursor 값 신뢰 금지).
    const { data: clipData, error: clipErr } = await supabaseAdmin
      .from('motion_clips')
      .select('id, started_at')
      .eq('id', clipId)
      .limit(1);
    if (clipErr) return motionLabelingDatabaseError(clipErr);
    const current = (clipData ?? [])[0] as { id: string; started_at: string } | undefined;
    if (!current) {
      return NextResponse.json(
        { detail: '대상을 찾을 수 없어.', code: 'not_found' },
        { status: 404 },
      );
    }

    const { data, error } = await supabaseAdmin.rpc('fn_list_motion_clip_labeling_queue', {
      p_reviewer_id: access.userId,
      p_is_owner: true,
      p_state: 'unreviewed',
      p_camera_ids: parsed.params.cameraIds,
      p_date_from: parsed.params.dateFrom,
      p_date_to: parsed.params.dateTo,
      p_media: parsed.params.media,
      p_cursor_started_at: current.started_at,
      p_cursor_id: current.id,
      p_limit: 1,
    });
    if (error) return motionRpcErrorResponse(error) ?? motionLabelingDatabaseError(error);

    const rows = (data ?? []) as { clip_id: string }[];
    return NextResponse.json({ next_clip_id: rows[0]?.clip_id ?? null });
  } catch (cause) {
    return motionLabelingDatabaseError(cause);
  }
}
