import { NextRequest, NextResponse } from 'next/server';

import { requireLabelingAccess } from '@/lib/labelingAccess';
import { BLIND_QUEUE_CLIP_COLUMNS } from '@/lib/labelingV2';
import { supabaseAdmin } from '@/lib/supabase';

export const runtime = 'nodejs';

// Blind GT 전용 큐. behavior_logs를 조회하지 않으므로 응답 payload에도 VLM 답이 없다.
//
// 접근: owner 또는 실제 labelers 멤버만(§8). pending/rejected/unregistered 는 여기서 차단된다.
// 제외 기준: 본인 clip_labeling_sessions.stage='completed' 만 제외한다(§4.8).
// - session 없음 → 일반 미검수 카드
// - gt_locked → session_stage='gt_locked'(‘VLM 검수 이어하기’)로 큐에 유지
// GT 잠금 시 호환 behavior_labels 가 먼저 저장돼도, 세션이 completed 가 아니면 큐에 남는다.
export async function GET(req: NextRequest) {
  const access = await requireLabelingAccess(req);
  if (!access.ok) return access.response;
  const { userId, isOwner } = access;

  const search = req.nextUrl.searchParams;
  const limit = Math.min(Math.max(Number(search.get('limit')) || 30, 1), 100);

  // 본인 세션의 stage 만 읽는다 — prediction_snapshot / VLM action 은 읽지 않아
  // 다른 blind 영상의 답이 큐 응답으로 새지 않는다(§4.8).
  const { data: sessionRows, error: sessionError } = await supabaseAdmin
    .from('clip_labeling_sessions')
    .select('clip_id, stage')
    .eq('reviewed_by', userId);
  if (sessionError) {
    return NextResponse.json(
      { detail: `supabase error: ${sessionError.message}` },
      { status: 502 },
    );
  }

  const completedIds: string[] = [];
  const gtLocked = new Set<string>();
  for (const row of sessionRows ?? []) {
    const clipId = row.clip_id as string | null;
    if (!clipId) continue;
    if (row.stage === 'completed') completedIds.push(clipId);
    else if (row.stage === 'gt_locked') gtLocked.add(clipId);
  }

  let query = supabaseAdmin
    .from('camera_clips')
    .select(BLIND_QUEUE_CLIP_COLUMNS)
    .eq('has_motion', true)
    .not('r2_key', 'is', null)
    .order('started_at', { ascending: false })
    .limit(limit + 1);

  // owner 는 본인 clip 만, labeler 는 전체 blind 풀을 본다(기존 큐 규약 유지).
  if (isOwner) query = query.eq('user_id', userId);
  if (completedIds.length) query = query.not('id', 'in', `(${completedIds.join(',')})`);
  if (search.get('cursor')) query = query.lt('started_at', search.get('cursor') as string);
  const cameraIds = search.get('camera_id')?.split(',').filter(Boolean) ?? [];
  if (cameraIds.length) query = query.in('camera_id', cameraIds);
  if (search.get('date_from')) query = query.gte('started_at', search.get('date_from') as string);
  if (search.get('date_to')) query = query.lte('started_at', search.get('date_to') as string);

  const { data, error } = await query;
  if (error) {
    return NextResponse.json({ detail: `supabase error: ${error.message}` }, { status: 502 });
  }
  const rows = data ?? [];
  const hasMore = rows.length > limit;
  const items = rows.slice(0, limit).map((clip) => ({
    ...clip,
    // stage 만 노출 — gt_locked 는 이어하기 배지, 그 외는 null.
    session_stage: gtLocked.has(clip.id as string) ? 'gt_locked' : null,
  }));
  return NextResponse.json({
    items,
    count: items.length,
    has_more: hasMore,
    next_cursor: hasMore ? items[items.length - 1]?.started_at ?? null : null,
  });
}
