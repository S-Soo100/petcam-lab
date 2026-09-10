import { NextRequest, NextResponse } from 'next/server';

import { highlightDatabaseError } from '@/lib/highlightV4Server';
import { requireLabelingAccess } from '@/lib/labelingAccess';
import { supabaseAdmin } from '@/lib/supabase';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

// GET /api/labeling-v4/progress — 요청자 기준 "오늘 내가 N개 · 남은 M개"(UX ③). 승인 사용자 누구나.
// 전체 clip 을 훑는 집계라 목록 방문 때만 부르고, 상세에선 클라이언트가 로컬로 가감한다(labelingV4Progress).
export async function GET(req: NextRequest) {
  const access = await requireLabelingAccess(req);
  if (!access.ok) return access.response;
  try {
    const { data, error } = await supabaseAdmin.rpc('fn_get_labeling_v4_progress', { p_viewer_id: access.userId });
    if (error) throw error;
    const p = (data ?? {}) as Record<string, unknown>;
    return NextResponse.json({
      activity_day: typeof p.activity_day === 'string' ? p.activity_day : null,
      labeled_today_me: Number(p.labeled_today_me ?? 0),
      labeled_today_all: Number(p.labeled_today_all ?? 0),
      unlabeled_all: Number(p.unlabeled_all ?? 0),
      unlabeled_mine: p.unlabeled_mine === null || p.unlabeled_mine === undefined ? null : Number(p.unlabeled_mine),
    });
  } catch (cause) {
    return highlightDatabaseError(cause);
  }
}
