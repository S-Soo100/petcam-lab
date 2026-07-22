import { NextRequest, NextResponse } from 'next/server';

import { requireProductionLabelingAccess } from '@/lib/labelingAccess';
import {
  decodeQueueCursor,
  encodeQueueCursor,
  InvalidQueueCursorError,
  type QueuePosition,
} from '@/lib/labelingQueueCursor';
import {
  mapMotionQueueRow,
  motionLabelingDatabaseError,
  motionRpcErrorResponse,
  type MotionQueueRow,
} from '@/lib/labelingV3Server';
import { supabaseAdmin } from '@/lib/supabase';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

// GET /api/labeling-v3/queue — motion_clips 최신순 큐(설계 §8).
//
// owner: motion_clips 전체(owner_id 필터 없음, 인증 자체가 접근권). state=all|unreviewed|label|hold|skip.
// labeler: owner_decision='label' + 재생가능 + 본인 미완료만. state 는 무시하고 항상 label 큐.
// 정렬 정본은 (started_at DESC, id DESC). cursor 는 versioned opaque 문자열이며, 잘못된 필터/커서는
// DB 접근 전에 400 으로 막는다(DB 502 와 다른 층위). RPC 는 raw provenance 를 반환하지 않고,
// 매퍼가 공개 8필드만 통과시킨다.

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
// strict RFC3339(offset 필수) — cursor helper 와 동일 계약. 관대한 Date.parse 를 막는다.
const RFC3339 = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})$/;
const OWNER_STATES = new Set(['unreviewed', 'label', 'hold', 'skip']);
// DB RPC 상한 100 안에서 limit+1 sentinel 한 행을 확보하려면 공개 페이지는 최대 99개다.
const MAX_PUBLIC_PAGE_SIZE = 99;

function badRequest(detail: string) {
  return NextResponse.json({ detail, code: 'invalid_request' }, { status: 400 });
}

function validDate(raw: string): boolean {
  return raw.length <= 64 && RFC3339.test(raw) && !Number.isNaN(Date.parse(raw));
}

interface QueueParams {
  state: string | null;
  cameraIds: string[] | null;
  dateFrom: string | null;
  dateTo: string | null;
  media: string | null;
  limit: number;
}

// query string → 검증된 RPC 파라미터. 잘못된 값은 error 문자열로(라우트가 400 매핑).
function parseQueueParams(
  search: URLSearchParams,
  isOwner: boolean,
): { params: QueueParams } | { error: string } {
  // limit: 미지정=30, 양의 정수만, 공개 페이지 99 상한 clamp.
  let limit = 30;
  const limitRaw = search.get('limit');
  if (limitRaw !== null) {
    if (!/^\d+$/.test(limitRaw) || Number(limitRaw) < 1) return { error: '잘못된 limit' };
    limit = Math.min(Number(limitRaw), MAX_PUBLIC_PAGE_SIZE);
  }

  // state: owner 만 필터. labeler 는 항상 label 큐(무시).
  let state: string | null = null;
  if (isOwner) {
    const raw = search.get('state');
    if (raw !== null && raw !== 'all') {
      if (!OWNER_STATES.has(raw)) return { error: '잘못된 state' };
      state = raw;
    }
  }

  // camera_id: 콤마 구분 UUID.
  let cameraIds: string[] | null = null;
  const camRaw = search.get('camera_id');
  if (camRaw) {
    const ids = camRaw.split(',').filter(Boolean);
    if (ids.some((id) => !UUID.test(id))) return { error: '잘못된 camera_id' };
    cameraIds = ids.length ? ids : null;
  }

  const dateFrom = search.get('date_from');
  if (dateFrom !== null && !validDate(dateFrom)) return { error: '잘못된 date_from' };
  const dateTo = search.get('date_to');
  if (dateTo !== null && !validDate(dateTo)) return { error: '잘못된 date_to' };

  const media = search.get('media');
  if (media !== null && media !== 'ready' && media !== 'unavailable') {
    return { error: '잘못된 media' };
  }

  return { params: { state, cameraIds, dateFrom, dateTo, media, limit } };
}

export async function GET(req: NextRequest) {
  const access = await requireProductionLabelingAccess(req);
  if (!access.ok) return access.response;
  const { userId, isOwner } = access;

  const search = req.nextUrl.searchParams;

  // cursor 해석은 DB 접근 이전. 잘못된 cursor 는 일반화된 400(DB 502 와 층위 분리).
  let cursor: QueuePosition | null;
  try {
    cursor = decodeQueueCursor(search.get('cursor'));
  } catch (error) {
    if (error instanceof InvalidQueueCursorError) return badRequest('페이지 위치가 올바르지 않아.');
    throw error;
  }

  const parsed = parseQueueParams(search, isOwner);
  if ('error' in parsed) return badRequest(parsed.error);
  const { state, cameraIds, dateFrom, dateTo, media, limit } = parsed.params;

  try {
    // limit+1 을 요청해 has_more 를 판정한다(RPC 는 자체적으로 100 상한 clamp).
    const { data, error } = await supabaseAdmin.rpc(
      'fn_list_motion_clip_labeling_queue',
      {
        p_reviewer_id: userId,
        p_is_owner: isOwner,
        p_state: state,
        p_camera_ids: cameraIds,
        p_date_from: dateFrom,
        p_date_to: dateTo,
        p_media: media,
        p_cursor_started_at: cursor?.startedAt ?? null,
        p_cursor_id: cursor?.id ?? null,
        p_limit: limit + 1,
      },
    );
    if (error) return motionRpcErrorResponse(error) ?? motionLabelingDatabaseError(error);

    const rows = (data ?? []) as MotionQueueRow[];
    const hasMore = rows.length > limit;
    const pageRows = hasMore ? rows.slice(0, limit) : rows;
    const items = pageRows.map(mapMotionQueueRow);
    const last = pageRows[pageRows.length - 1];
    // next_cursor 는 DB started_at 원문(마이크로초)을 그대로 담는다 — 재직렬화 금지.
    const nextCursor =
      hasMore && last ? encodeQueueCursor({ startedAt: last.started_at, id: last.clip_id }) : null;

    return NextResponse.json({ items, next_cursor: nextCursor, has_more: hasMore });
  } catch (cause) {
    return motionLabelingDatabaseError(cause);
  }
}
