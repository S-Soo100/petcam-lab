import { NextRequest, NextResponse } from 'next/server';

import { verifyBearer } from '@/lib/clipPerms';
import { supabaseAdmin } from '@/lib/supabase';

export const runtime = 'nodejs';

// Blind GT 전용 큐. behavior_logs를 조회하지 않으므로 응답 payload에도 VLM 답이 없다.
export async function GET(req: NextRequest) {
  const authResult = await verifyBearer(req);
  if (!authResult.ok) return authResult.response;
  const userId = authResult.auth.userId;
  const search = req.nextUrl.searchParams;
  const limit = Math.min(Math.max(Number(search.get('limit')) || 30, 1), 100);

  const [{ data: labelerRows, error: labelerError }, { data: ownLabels, error: labelError }] =
    await Promise.all([
      supabaseAdmin.from('labelers').select('user_id').eq('user_id', userId).limit(1),
      supabaseAdmin.from('behavior_labels').select('clip_id').eq('labeled_by', userId),
    ]);
  if (labelerError || labelError) {
    return NextResponse.json(
      { detail: `supabase error: ${(labelerError ?? labelError)?.message}` },
      { status: 502 },
    );
  }

  let query = supabaseAdmin
    .from('camera_clips')
    .select('id,user_id,camera_id,pet_id,started_at,ended_at,duration_sec,has_motion,r2_key,thumbnail_r2_key')
    .eq('has_motion', true)
    .not('r2_key', 'is', null)
    .order('started_at', { ascending: false })
    .limit(limit + 1);

  if ((labelerRows ?? []).length === 0) query = query.eq('user_id', userId);
  const labeledIds = (ownLabels ?? []).map((row) => row.clip_id).filter(Boolean);
  if (labeledIds.length) query = query.not('id', 'in', `(${labeledIds.join(',')})`);
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
  const items = rows.slice(0, limit);
  return NextResponse.json({
    items,
    count: items.length,
    has_more: hasMore,
    next_cursor: hasMore ? items[items.length - 1]?.started_at ?? null : null,
  });
}
