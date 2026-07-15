import { NextRequest, NextResponse } from 'next/server';

import { requireOwner } from '@/lib/labelingAccess';
import { supabaseAdmin } from '@/lib/supabase';
import { databaseUnavailable } from '@/lib/apiErrors';
import {
  applyTriageClipFilters,
  applyTriageStateFilter,
  decodeTriageCursor,
  encodeTriageCursor,
  mapTriageRowToListItem,
  parseTriageClipFilters,
  type TriageClipFilters,
  type TriageJoinRow,
  type TriageListState,
} from '@/lib/labelingTriageServer';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const STATES = ['pending', 'skipped', 'labeled'] as const;

// clip_labeling_triage + camera_clips(embed) 조회 컬럼. evidence_snapshot 은 select 하지 않는다.
const TRIAGE_SELECT =
  'clip_id,suggested_route,suggestion_reason,suggestion_source,policy_version,' +
  'owner_decision,decided_at,decision_note,updated_at,' +
  'camera_clips!inner(id,camera_id,started_at,duration_sec,r2_key,thumbnail_r2_key)';

// GET /api/labeling-triage?state=&cursor=&limit=&date_from=&date_to=&camera_id=
// owner-only(설계 §7). 목록 + 탭별 건수 + 커서 페이지네이션. raw evidence 비노출.
export async function GET(req: NextRequest) {
  const owner = await requireOwner(req);
  if (!owner.ok) return owner.response;

  const search = req.nextUrl.searchParams;

  const stateParam = search.get('state') ?? 'pending';
  if (!STATES.includes(stateParam as TriageListState)) {
    return NextResponse.json({ detail: `잘못된 state: ${stateParam}` }, { status: 400 });
  }
  const state = stateParam as TriageListState;

  const rawLimit = Number(search.get('limit'));
  if (search.get('limit') !== null && (!Number.isInteger(rawLimit) || rawLimit < 1 || rawLimit > 100)) {
    return NextResponse.json({ detail: '잘못된 limit' }, { status: 400 });
  }
  const limit = rawLimit >= 1 && rawLimit <= 100 ? rawLimit : 30;

  // 촬영일·카메라 필터 검증(공유 헬퍼). 잘못된 날짜/카메라는 400.
  const parsed = parseTriageClipFilters(search);
  if ('error' in parsed) {
    return NextResponse.json({ detail: parsed.error }, { status: 400 });
  }
  const filters: TriageClipFilters = parsed.filters;

  let cursor: { updatedAt: string; clipId: string } | null = null;
  const cursorParam = search.get('cursor');
  if (cursorParam) {
    try {
      cursor = decodeTriageCursor(cursorParam);
    } catch {
      return NextResponse.json({ detail: '잘못된 cursor' }, { status: 400 });
    }
  }

  try {
    // 목록 — updated_at DESC, clip_id DESC 안정 정렬. limit+1 로 has_more 판정.
    let listQuery = supabaseAdmin.from('clip_labeling_triage').select(TRIAGE_SELECT);
    listQuery = applyTriageStateFilter(listQuery, state);
    listQuery = applyTriageClipFilters(listQuery, filters);
    if (cursor) {
      // keyset: (updated_at < c.u) OR (updated_at = c.u AND clip_id < c.clip)
      listQuery = listQuery.or(
        `updated_at.lt.${cursor.updatedAt},and(updated_at.eq.${cursor.updatedAt},clip_id.lt.${cursor.clipId})`,
      );
    }
    const { data, error } = await listQuery
      .order('updated_at', { ascending: false })
      .order('clip_id', { ascending: false })
      .limit(limit + 1);
    if (error) throw error;

    const rows = (data ?? []) as unknown as TriageJoinRow[];
    const hasMore = rows.length > limit;
    const pageRows = hasMore ? rows.slice(0, limit) : rows;
    const items = pageRows.map(mapTriageRowToListItem);
    const last = items[items.length - 1];
    const nextCursor =
      hasMore && last
        ? encodeTriageCursor({ updatedAt: last.updated_at, clipId: last.clip_id })
        : null;

    // 탭별 건수 — 목록과 동일 필터를 적용한 head count 3회. evidence 를 읽지 않는다.
    const counts = await countByState(filters);

    return NextResponse.json({
      items,
      counts,
      has_more: hasMore,
      next_cursor: nextCursor,
    });
  } catch (cause) {
    return databaseUnavailable('labeling triage list', cause);
  }
}

async function countByState(
  filters: TriageClipFilters,
): Promise<{ pending: number; skipped: number; labeled: number }> {
  const one = async (state: TriageListState): Promise<number> => {
    // 필터를 camera_clips embed 컬럼에 걸려면 count select 에도 inner join 을 둔다.
    let q = supabaseAdmin
      .from('clip_labeling_triage')
      .select('clip_id,camera_clips!inner(camera_id,started_at)', {
        count: 'exact',
        head: true,
      });
    q = applyTriageStateFilter(q, state);
    q = applyTriageClipFilters(q, filters);
    const { count, error } = await q;
    if (error) throw error;
    return count ?? 0;
  };
  const [pending, skipped, labeled] = await Promise.all([
    one('pending'),
    one('skipped'),
    one('labeled'),
  ]);
  return { pending, skipped, labeled };
}
