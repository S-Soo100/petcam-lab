import { NextRequest, NextResponse } from 'next/server';

import { requireProductionLabelingAccess } from '@/lib/labelingAccess';
import { BLIND_QUEUE_CLIP_COLUMNS } from '@/lib/labelingV2';
import { collectQueuePage } from '@/lib/labelingQueue';
import {
  decodeQueueCursor,
  encodeQueueCursor,
  InvalidQueueCursorError,
  type QueuePosition,
} from '@/lib/labelingQueueCursor';
import { supabaseAdmin } from '@/lib/supabase';
import { databaseUnavailable } from '@/lib/apiErrors';

export const runtime = 'nodejs';

// Blind GT 전용 큐. behavior_logs를 조회하지 않으므로 응답 payload에도 VLM 답이 없다.
//
// 접근: owner 또는 실제 labelers 멤버만(§8). pending/rejected/unregistered 는 여기서 차단된다.
// 제외 기준: 본인 clip_labeling_sessions.stage='completed' 만 제외한다(§4.8).
// - session 없음 → 일반 미검수 카드
// - gt_locked → session_stage='gt_locked'(‘VLM 검수 이어하기’)로 큐에 유지
// GT 잠금 시 호환 behavior_labels 가 먼저 저장돼도, 세션이 completed 가 아니면 큐에 남는다.
//
// 정렬 정본은 (started_at DESC, id DESC)(설계 §4.1). started_at 하나로는 같은 시각 clip
// 순서가 결정론적이지 않아 다음 페이지에서 누락이 생기므로 id 를 동률 해소키로 함께 쓴다.
// cursor 는 versioned opaque 문자열이며, 잘못된 cursor 는 DB 접근 전에 400 으로 막는다.
export async function GET(req: NextRequest) {
  // production 게이트 — 미완료 labeler 는 403 tutorial_required(설계 §12).
  const access = await requireProductionLabelingAccess(req);
  if (!access.ok) return access.response;
  const { userId, isOwner } = access;

  const search = req.nextUrl.searchParams;
  const limit = Math.min(Math.max(Number(search.get('limit')) || 30, 1), 100);

  // cursor 해석은 DB 접근 이전. 잘못된 cursor 는 일반화된 400 invalid_cursor 로,
  // DB 장애(502)와 다른 층위로 분리한다(설계 §7). 이 분기는 databaseUnavailable catch 밖.
  let cursor: QueuePosition | null;
  try {
    cursor = decodeQueueCursor(search.get('cursor'));
  } catch (error) {
    if (error instanceof InvalidQueueCursorError) {
      return NextResponse.json(
        { detail: '페이지 위치가 올바르지 않아.', code: 'invalid_cursor' },
        { status: 400 },
      );
    }
    throw error;
  }

  const cameraIds = search.get('camera_id')?.split(',').filter(Boolean) ?? [];
  try {
    const page = await collectQueuePage({
      limit,
      cursor,
      fetchCandidates: async (scanCursor, batchSize) => {
        let query = supabaseAdmin
          .from('camera_clips')
          .select(BLIND_QUEUE_CLIP_COLUMNS)
          .eq('has_motion', true)
          .not('r2_key', 'is', null)
          // 정본 정렬키 두 개 — 같은 started_at 은 id DESC 로 결정론적 순서.
          .order('started_at', { ascending: false })
          .order('id', { ascending: false })
          .limit(batchSize);
        // owner 는 본인 clip 만, labeler 는 전체 blind 풀을 본다.
        if (isOwner) query = query.eq('user_id', userId);
        // 복합 keyset: started_at 이 더 오래됐거나(<), 같은 시각이면 id 가 더 작은(<) clip 만.
        if (scanCursor) {
          query = query.or(
            `started_at.lt.${scanCursor.startedAt},and(started_at.eq.${scanCursor.startedAt},id.lt.${scanCursor.id})`,
          );
        }
        if (cameraIds.length) query = query.in('camera_id', cameraIds);
        if (search.get('date_from')) query = query.gte('started_at', search.get('date_from') as string);
        if (search.get('date_to')) query = query.lte('started_at', search.get('date_to') as string);
        const { data, error } = await query;
        if (error) throw error;
        return data ?? [];
      },
      // 후보 clip ID만 조회한다. prediction_snapshot/VLM action은 select하지 않는다.
      fetchStages: async (clipIds) => {
        if (clipIds.length === 0) return [];
        const { data, error } = await supabaseAdmin
          .from('clip_labeling_sessions')
          .select('clip_id, stage')
          .eq('reviewed_by', userId)
          .in('clip_id', clipIds);
        if (error) throw error;
        return data ?? [];
      },
      // 후보 배치의 triage 상태만 조회한다(설계 §9). suggested_route/owner_decision 로
      // 유효 상태를 접어 pending/skipped 를 제외한다. evidence_snapshot 은 select 안 함.
      // 조회 실패는 throw → databaseUnavailable 로 502. skip 된 clip 을 라벨러에게
      // 다시 노출하지 않도록 DB 장애 시 fail-open 하지 않는다(설계 §9).
      fetchTriage: async (clipIds) => {
        if (clipIds.length === 0) return [];
        const { data, error } = await supabaseAdmin
          .from('clip_labeling_triage')
          .select('clip_id,suggested_route,owner_decision')
          .in('clip_id', clipIds);
        if (error) throw error;
        return data ?? [];
      },
    });
    return NextResponse.json({
      items: page.items,
      count: page.items.length,
      has_more: page.hasMore,
      // 내부 큐 scan 은 복합 위치 객체를 쓰지만, 외부 계약은 opaque 문자열만 노출한다.
      next_cursor: page.nextCursor ? encodeQueueCursor(page.nextCursor) : null,
    });
  } catch (cause) {
    return databaseUnavailable('labeling queue', cause);
  }
}
