import { NextRequest, NextResponse } from 'next/server';

import { highlightDatabaseError, highlightRpcErrorResponse } from '@/lib/highlightV4Server';
import { requireLabelingAccess } from '@/lib/labelingAccess';
import { decodeQueueCursor, encodeQueueCursor, InvalidQueueCursorError } from '@/lib/labelingQueueCursor';
import { readGmeActiveContract } from '@/lib/labelingV3Server';
import { mapV4ClipRow, parseV4ListRequest, type V4ClipRow } from '@/lib/labelingV4Server';
import { supabaseAdmin } from '@/lib/supabase';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

function badRequest(detail: string) {
  return NextResponse.json({ detail, code: 'invalid_request' }, { status: 400 });
}

// GET /api/labeling-v4/clips?scope=mine|all&camera_id=&label_state=&highlight_state=&cursor=&limit=
// 정렬 (started_at DESC, id DESC). 배정은 scope=mine 의 필터일 뿐 권한이 아니다(v4 스펙 §4.1).
export async function GET(req: NextRequest) {
  const access = await requireLabelingAccess(req);
  if (!access.ok) return access.response;
  const sp = req.nextUrl.searchParams;
  let cursor;
  try { cursor = decodeQueueCursor(sp.get('cursor')); } catch (e) { if (e instanceof InvalidQueueCursorError) return badRequest('cursor 가 잘못됐어.'); throw e; }
  let parsed;
  try { parsed = parseV4ListRequest(sp); } catch (e) { return badRequest(`요청 값이 잘못됐어(${(e as Error).message}).`); }
  try {
    const contract = readGmeActiveContract();
    // limit+1 조회로 has_more 판정 — count 쿼리 없이 다음 페이지 유무를 안다.
    const { data, error } = await supabaseAdmin.rpc('fn_list_labeling_v4_clips', {
      p_viewer_id: access.userId, p_is_owner: access.isOwner, p_scope: parsed.scope, p_camera_ids: parsed.cameraIds,
      p_label_state: parsed.labelState, p_highlight_state: parsed.highlightState,
      p_engine_schema_version: contract.engine_schema_version, p_algorithm_version: contract.algorithm_version, p_detector_identity: contract.detector_identity,
      p_cursor_started_at: cursor?.startedAt ?? null, p_cursor_id: cursor?.id ?? null, p_limit: parsed.limit + 1,
    });
    if (error) return highlightRpcErrorResponse(error) ?? highlightDatabaseError(error);
    const rows = (data ?? []) as V4ClipRow[];
    const hasMore = rows.length > parsed.limit;
    const page = hasMore ? rows.slice(0, parsed.limit) : rows;
    const items = page.map(mapV4ClipRow);
    const last = items[items.length - 1];
    return NextResponse.json({ items, has_more: hasMore, next_cursor: hasMore && last ? encodeQueueCursor({ startedAt: last.started_at, id: last.id }) : null });
  } catch (cause) {
    return highlightDatabaseError(cause);
  }
}
