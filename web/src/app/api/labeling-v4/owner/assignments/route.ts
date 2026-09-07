import { NextRequest, NextResponse } from 'next/server';

import { highlightDatabaseError, highlightRpcErrorResponse } from '@/lib/highlightV4Server';
import { requireOwner } from '@/lib/labelingAccess';
import { supabaseAdmin } from '@/lib/supabase';
import { resolveReviewerName } from '../../_access';
import { UUID_RE } from '@/lib/uuid';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

// GET /api/labeling-v4/owner/assignments — 멤버(배정 카메라 포함) + 카메라 옵션.
export async function GET(req: NextRequest) {
  const owner = await requireOwner(req);
  if (!owner.ok) return owner.response;
  try {
    const members = await supabaseAdmin.rpc('fn_list_labeling_v4_members', {});
    if (members.error) throw members.error;
    const cameras = await supabaseAdmin.rpc('fn_list_labeling_v4_cameras', { p_viewer_id: owner.userId });
    if (cameras.error) throw cameras.error;
    return NextResponse.json({
      // SQL 은 raw display_name(nullable) — 표시명은 단일 resolver 로.
      members: ((members.data ?? []) as { user_id: string; display_name: string | null; camera_ids: string[] }[]).map((m) => ({
        user_id: m.user_id,
        display_name: resolveReviewerName({ reviewerId: m.user_id, displayName: m.display_name ?? null }),
        camera_ids: m.camera_ids ?? [],
      })),
      cameras: ((cameras.data ?? []) as { camera_id: string; camera_name: string; assigned: boolean }[]).map((c) => ({ id: c.camera_id, name: c.camera_name, assigned: Boolean(c.assigned) })),
    });
  } catch (cause) {
    return highlightDatabaseError(cause);
  }
}

// PUT /api/labeling-v4/owner/assignments { user_id, camera_ids[] } — 해당 멤버 배정을 통째로 교체.
export async function PUT(req: NextRequest) {
  const owner = await requireOwner(req);
  if (!owner.ok) return owner.response;
  let body: { user_id?: unknown; camera_ids?: unknown };
  try { body = await req.json(); } catch { return NextResponse.json({ detail: 'JSON 본문이 필요해.', code: 'invalid_request' }, { status: 400 }); }
  if (typeof body.user_id !== 'string' || !UUID_RE.test(body.user_id) || !Array.isArray(body.camera_ids) || !body.camera_ids.every((c) => typeof c === 'string' && UUID_RE.test(c))) {
    return NextResponse.json({ detail: 'user_id/camera_ids 가 잘못됐어.', code: 'invalid_request' }, { status: 400 });
  }
  try {
    const { data, error } = await supabaseAdmin.rpc('fn_set_labeler_camera_assignments', { p_user_id: body.user_id, p_camera_ids: body.camera_ids, p_actor_id: owner.userId });
    if (error) return highlightRpcErrorResponse(error) ?? highlightDatabaseError(error);
    return NextResponse.json({ camera_ids: ((data ?? []) as { camera_id: string }[]).map((r) => r.camera_id) });
  } catch (cause) {
    return highlightDatabaseError(cause);
  }
}
