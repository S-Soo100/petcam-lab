import { NextRequest, NextResponse } from 'next/server';

import { requireProductionLabelingAccess } from '@/lib/labelingAccess';
import { BLIND_QUEUE_CLIP_COLUMNS } from '@/lib/labelingV2';
import { collectQueuePage } from '@/lib/labelingQueue';
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
export async function GET(req: NextRequest) {
  // production 게이트 — 미완료 labeler 는 403 tutorial_required(설계 §12).
  const access = await requireProductionLabelingAccess(req);
  if (!access.ok) return access.response;
  const { userId, isOwner } = access;

  const search = req.nextUrl.searchParams;
  const limit = Math.min(Math.max(Number(search.get('limit')) || 30, 1), 100);

  const cameraIds = search.get('camera_id')?.split(',').filter(Boolean) ?? [];
  try {
    const page = await collectQueuePage({
      limit,
      cursor: search.get('cursor'),
      fetchCandidates: async (cursor, batchSize) => {
        let query = supabaseAdmin
          .from('camera_clips')
          .select(BLIND_QUEUE_CLIP_COLUMNS)
          .eq('has_motion', true)
          .not('r2_key', 'is', null)
          .order('started_at', { ascending: false })
          .limit(batchSize);
        // owner 는 본인 clip 만, labeler 는 전체 blind 풀을 본다.
        if (isOwner) query = query.eq('user_id', userId);
        if (cursor) query = query.lt('started_at', cursor);
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
    });
    return NextResponse.json({
      items: page.items,
      count: page.items.length,
      has_more: page.hasMore,
      next_cursor: page.nextCursor,
    });
  } catch (cause) {
    return databaseUnavailable('labeling queue', cause);
  }
}
