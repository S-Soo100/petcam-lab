import { NextRequest, NextResponse } from 'next/server';

import { supabaseAdmin } from '@/lib/supabase';
import {
  blindBadRequest,
  blindDatabaseError,
  blindRpcErrorResponse,
  isValidUuid,
  mapBlindQueueRow,
  requireBlindLabeler,
  type BlindQueueRow,
} from '@/lib/motionBlindReviewServer';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

// GET /api/labeling-v3/blind/canary/[cohortId] — open canary 의 자기 slot + 진행 집계(설계 §6.3).
//
// live 큐·진행률·export 와 분리된 격리 cohort. 열린 canary 만 노출하고, 닫힘/미존재 cohort 는
// 안전한 만료 상태로 접는다. reviewer id 는 bearer 에서만. 상대 원문 0.
export async function GET(req: NextRequest, { params }: { params: { cohortId: string } }) {
  const access = await requireBlindLabeler(req);
  if (!access.ok) return access.response;
  const { userId } = access;

  if (!isValidUuid(params.cohortId)) return blindBadRequest('잘못된 cohort id');
  const cohortId = params.cohortId;

  try {
    const { data: cohortData, error: cohortErr } = await supabaseAdmin
      .from('motion_blind_review_cohorts')
      .select('id, status, kind')
      .eq('id', cohortId)
      .limit(1);
    if (cohortErr) throw cohortErr;
    const cohort = (cohortData ?? [])[0] as { status?: string; kind?: string } | undefined;
    if (!cohort || cohort.status !== 'open' || cohort.kind !== 'canary') {
      return NextResponse.json(
        { detail: '검증 링크가 만료됐어.', code: 'cohort_closed' },
        { status: 410 },
      );
    }

    // 자기 canary slot 미제출분(작업 목록). cohort scope 로 고정 — live 는 섞이지 않는다.
    const { data, error } = await supabaseAdmin.rpc('fn_list_motion_blind_queue', {
      p_reviewer_id: userId,
      p_activity_day: null,
      p_cohort_kind: 'canary',
      p_cohort_id: cohortId,
      p_cursor_started_at: null,
      p_cursor_id: null,
      p_limit: 100,
    });
    if (error) return blindRpcErrorResponse(error) ?? blindDatabaseError(error);
    const items = ((data ?? []) as BlindQueueRow[]).map(mapBlindQueueRow);

    // 진행 집계(내 slot 총계/제출 수). 상대 판정은 세지 않는다.
    const { data: slotData, error: slotErr } = await supabaseAdmin
      .from('motion_clip_review_slots')
      .select('submitted_at')
      .eq('reviewer_id', userId)
      .eq('cohort_kind', 'canary')
      .eq('cohort_id', cohortId);
    if (slotErr) throw slotErr;
    const slots = (slotData ?? []) as { submitted_at: string | null }[];
    const total = slots.length;
    const submitted = slots.filter((s) => s.submitted_at != null).length;

    return NextResponse.json({
      cohort_id: cohortId,
      items,
      total_count: total,
      submitted_count: submitted,
    });
  } catch (cause) {
    return blindDatabaseError(cause);
  }
}
