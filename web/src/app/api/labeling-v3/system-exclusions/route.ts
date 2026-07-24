import { NextRequest, NextResponse } from 'next/server';

import { requireOwner } from '@/lib/labelingAccess';
import {
  decodeQueueCursor,
  encodeQueueCursor,
  InvalidQueueCursorError,
  type QueuePosition,
} from '@/lib/labelingQueueCursor';
import {
  mapMotionSystemExclusionRow,
  motionLabelingDatabaseError,
  motionRpcErrorResponse,
  type MotionSystemExclusionRow,
} from '@/lib/labelingV3Server';
import { supabaseAdmin } from '@/lib/supabase';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

// GET /api/labeling-v3/system-exclusions — Owner 전용 짧은 영상 자동 제외 목록(설계 §6.2).
//
// quarantined/media_deleted/deletion_blocked 만 (detected_at DESC, id DESC) keyset 으로 반환.
// requireOwner 통과 전에는 DB 접근 0. cursor 는 opaque base64(잘못된 cursor 는 DB 전에 400).
// RPC 는 raw r2_key/lease/worker/fingerprint/actor 를 주지 않고, 매퍼가 공개 필드만 통과시키며
// cursor_detected_at/cursor_id 는 다음 페이지 토큰 조립에만 쓰고 응답 item 에는 담지 않는다.

const PAGE_SIZE = 50;

function badRequest(detail: string) {
  return NextResponse.json({ detail, code: 'invalid_request' }, { status: 400 });
}

export async function GET(req: NextRequest) {
  const owner = await requireOwner(req);
  if (!owner.ok) return owner.response;

  let cursor: QueuePosition | null;
  try {
    cursor = decodeQueueCursor(req.nextUrl.searchParams.get('cursor'));
  } catch (error) {
    if (error instanceof InvalidQueueCursorError) return badRequest('페이지 위치가 올바르지 않아.');
    throw error;
  }

  try {
    // PAGE_SIZE+1 을 요청해 has_more 판정(RPC 는 자체적으로 100 상한 clamp).
    const { data, error } = await supabaseAdmin.rpc('fn_list_short_clip_system_exclusions', {
      p_cursor_detected_at: cursor?.startedAt ?? null,
      p_cursor_id: cursor?.id ?? null,
      p_limit: PAGE_SIZE + 1,
    });
    if (error) return motionRpcErrorResponse(error) ?? motionLabelingDatabaseError(error);

    const rows = (data ?? []) as MotionSystemExclusionRow[];
    const hasMore = rows.length > PAGE_SIZE;
    const pageRows = hasMore ? rows.slice(0, PAGE_SIZE) : rows;
    const items = pageRows.map(mapMotionSystemExclusionRow);
    const last = pageRows[pageRows.length - 1];
    // 다음 커서는 마지막 row 의 (detected_at, exclusion id)를 opaque 로 감싼다(공개 item 엔 없음).
    const nextCursor =
      hasMore && last
        ? encodeQueueCursor({ startedAt: last.cursor_detected_at, id: last.cursor_id })
        : null;

    return NextResponse.json({ items, next_cursor: nextCursor, has_more: hasMore });
  } catch (cause) {
    return motionLabelingDatabaseError(cause);
  }
}
