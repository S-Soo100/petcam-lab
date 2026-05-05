import { NextRequest, NextResponse } from 'next/server';
import { supabaseAdmin } from '@/lib/supabase';

export const dynamic = 'force-dynamic';

// PoC 대시보드 stats — owner-only (DEV_USER_ID 본인만).
// 라벨링 웹(prod) 에는 DEV_USER_ID/ROUND1_CAMERA_ID env 없음 → 404.
// page.tsx 가 401/403/404 받으면 /labeling 또는 /labeling/login 으로 redirect.
export async function GET(req: NextRequest) {
  const auth = req.headers.get('authorization') || '';
  const token = auth.startsWith('Bearer ') ? auth.slice(7) : null;
  if (!token) {
    return NextResponse.json({ detail: 'unauthorized' }, { status: 401 });
  }

  const { data: { user }, error } = await supabaseAdmin.auth.getUser(token);
  if (error || !user) {
    return NextResponse.json({ detail: 'invalid token' }, { status: 401 });
  }

  const devUserId = process.env.DEV_USER_ID;
  const round1CameraId = process.env.ROUND1_CAMERA_ID;
  if (!devUserId || !round1CameraId) {
    return NextResponse.json({ detail: 'PoC dashboard disabled' }, { status: 404 });
  }

  if (user.id !== devUserId) {
    return NextResponse.json({ detail: 'forbidden' }, { status: 403 });
  }

  const [{ count: poolCount }, { data: gtRows }, { data: vlmRows }] = await Promise.all([
    supabaseAdmin
      .from('camera_clips')
      .select('id', { count: 'exact', head: true })
      .eq('user_id', devUserId)
      .or(`source.eq.upload,camera_id.eq.${round1CameraId}`)
      .eq('has_motion', true),
    supabaseAdmin.from('behavior_logs').select('clip_id').eq('source', 'human'),
    supabaseAdmin.from('behavior_logs').select('clip_id').eq('source', 'vlm'),
  ]);
  const gtIds = new Set((gtRows ?? []).map((r) => r.clip_id as string));
  const vlmIds = new Set((vlmRows ?? []).map((r) => r.clip_id as string));
  return NextResponse.json({
    pool: poolCount ?? 0,
    labeled: gtIds.size,
    inferred: vlmIds.size,
    paired: Array.from(vlmIds).filter((id) => gtIds.has(id)).length,
  });
}
