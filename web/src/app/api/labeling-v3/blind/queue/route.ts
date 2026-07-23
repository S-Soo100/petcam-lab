import { NextRequest, NextResponse } from 'next/server';

import { supabaseAdmin } from '@/lib/supabase';
import {
  blindBadRequest,
  blindDatabaseError,
  blindRpcErrorResponse,
  decodeBlindCursor,
  encodeBlindCursor,
  InvalidBlindCursorError,
  isValidActivityDay,
  mapBlindQueueRow,
  requireBlindLabeler,
  type BlindQueuePosition,
  type BlindQueueRow,
  type BlindQueueScope,
} from '@/lib/motionBlindReviewServer';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

// GET /api/labeling-v3/blind/queue?activity_day=YYYY-MM-DD&cursor=..&limit=..
//
// 본인 미제출 live slot 최신순 keyset(설계 §4). live 전용 — cohort scope 는 항상 live/null 로
// 고정하고, 다른 날짜나 canary scope 로 복사된 cursor 는 DB 접근 전에 400 으로 거부한다.
function parseLimit(raw: string | null): number | null {
  if (raw === null) return 30;
  if (!/^\d{1,3}$/.test(raw)) return null;
  const n = Number(raw);
  if (n < 1 || n > 100) return null;
  return n;
}

export async function GET(req: NextRequest) {
  const access = await requireBlindLabeler(req);
  if (!access.ok) return access.response;
  const { userId } = access;

  const search = req.nextUrl.searchParams;
  const activityDay = search.get('activity_day');
  if (!isValidActivityDay(activityDay)) return blindBadRequest('활동일이 올바르지 않아.');

  const limit = parseLimit(search.get('limit'));
  if (limit === null) return blindBadRequest('페이지 크기가 올바르지 않아.');

  // live 전용 scope. cursor 는 scope 를 embed 하며 decode 시점에 scope 불일치를 400 으로 막는다.
  const scope: BlindQueueScope = { activityDay, cohortKind: 'live', cohortId: null };
  let cursor: BlindQueuePosition | null;
  try {
    cursor = decodeBlindCursor(search.get('cursor'), scope);
  } catch (error) {
    if (error instanceof InvalidBlindCursorError) return blindBadRequest('페이지 위치가 올바르지 않아.');
    throw error;
  }

  try {
    const { data, error } = await supabaseAdmin.rpc('fn_list_motion_blind_queue', {
      p_reviewer_id: userId,
      p_activity_day: activityDay,
      p_cohort_kind: 'live',
      p_cohort_id: null,
      p_cursor_started_at: cursor?.startedAt ?? null,
      p_cursor_id: cursor?.id ?? null,
      p_limit: limit + 1,
    });
    if (error) return blindRpcErrorResponse(error) ?? blindDatabaseError(error);

    const rows = (data ?? []) as BlindQueueRow[];
    const hasMore = rows.length > limit;
    const pageRows = hasMore ? rows.slice(0, limit) : rows;
    const items = pageRows.map(mapBlindQueueRow);
    const last = pageRows[pageRows.length - 1];
    const nextCursor =
      hasMore && last ? encodeBlindCursor(scope, { startedAt: last.started_at, id: last.clip_id }) : null;

    return NextResponse.json({ items, next_cursor: nextCursor, has_more: hasMore });
  } catch (cause) {
    return blindDatabaseError(cause);
  }
}
