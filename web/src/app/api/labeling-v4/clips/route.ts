import { NextRequest, NextResponse } from 'next/server';

import { highlightDatabaseError, highlightRpcErrorResponse } from '@/lib/highlightV4Server';
import { requireLabelingAccess } from '@/lib/labelingAccess';
import { decodeQueueCursor, encodeQueueCursor, InvalidQueueCursorError } from '@/lib/labelingQueueCursor';
import { readGmeActiveContract } from '@/lib/labelingV3Server';
import { mapV4ClipRow, parseV4ListRequest, type V4ClipRow } from '@/lib/labelingV4Server';
import { presignGet } from '@/lib/r2';
import { supabaseAdmin } from '@/lib/supabase';
import { resolveReviewerName } from '../_access';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

function badRequest(detail: string) {
  return NextResponse.json({ detail, code: 'invalid_request' }, { status: 400 });
}

const THUMBNAIL_TTL_SEC = 600;

// 카드 썸네일(UX ⑦): motion_clips.thumbnail_key 를 한 번에 조회해 짧은 서명 URL 로 붙인다. 실패는 null(목록은 계속).
async function attachThumbnails(items: { id: string; thumbnail_url: string | null }[]): Promise<void> {
  if (items.length === 0) return;
  try {
    const { data, error } = await supabaseAdmin.from('motion_clips').select('id, thumbnail_key').in('id', items.map((i) => i.id));
    if (error) throw error;
    const keys = new Map<string, string>();
    for (const row of (data ?? []) as { id?: unknown; thumbnail_key?: unknown }[]) {
      if (typeof row.id === 'string' && typeof row.thumbnail_key === 'string' && row.thumbnail_key) keys.set(row.id, row.thumbnail_key);
    }
    await Promise.all(items.map(async (it) => {
      const key = keys.get(it.id);
      if (!key) return;
      try { it.thumbnail_url = await presignGet(key, THUMBNAIL_TTL_SEC); } catch { it.thumbnail_url = null; }
    }));
  } catch {
    // 썸네일은 보조 정보 — 조회 실패해도 목록은 그대로 돌려준다.
  }
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
      p_label_state: parsed.labelState, p_highlight_state: parsed.highlightState, p_behavior_flag: parsed.behaviorFlag,
      p_engine_schema_version: contract.engine_schema_version, p_algorithm_version: contract.algorithm_version, p_detector_identity: contract.detector_identity,
      p_cursor_started_at: cursor?.startedAt ?? null, p_cursor_id: cursor?.id ?? null, p_limit: parsed.limit + 1,
    });
    if (error) return highlightRpcErrorResponse(error) ?? highlightDatabaseError(error);
    const rows = (data ?? []) as V4ClipRow[];
    const hasMore = rows.length > parsed.limit;
    const page = hasMore ? rows.slice(0, parsed.limit) : rows;
    // reviewer_id·raw display_name 은 표시명으로만 접는다 — 라벨러 응답에 reviewer UUID 를 싣지 않는다.
    const items = page.map((r) => mapV4ClipRow(r, (reviewerId, displayName) => resolveReviewerName({ reviewerId, displayName })));
    await attachThumbnails(items);
    const last = items[items.length - 1];
    return NextResponse.json({ items, has_more: hasMore, next_cursor: hasMore && last ? encodeQueueCursor({ startedAt: last.started_at, id: last.id }) : null });
  } catch (cause) {
    return highlightDatabaseError(cause);
  }
}
