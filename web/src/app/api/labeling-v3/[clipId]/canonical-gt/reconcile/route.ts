import { NextRequest, NextResponse } from 'next/server';

import { requireOwner } from '@/lib/labelingAccess';
import { GroundTruthValidationError, validateGroundTruth, type GroundTruthInput } from '@/lib/labelingV2';
import { motionLabelingDatabaseError, motionRpcErrorResponse } from '@/lib/labelingV3Server';
import { supabaseAdmin } from '@/lib/supabase';

export const runtime = 'nodejs';
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function badRequest(detail: string) {
  return NextResponse.json({ detail, code: 'invalid_request' }, { status: 400 });
}

export async function POST(req: NextRequest, { params }: { params: { clipId: string } }) {
  const owner = await requireOwner(req);
  if (!owner.ok) return owner.response;
  if (process.env.LABELING_CANONICAL_GT_OWNER_WRITE_ENABLED !== 'true') {
    return NextResponse.json({ detail: 'not found' }, { status: 404 });
  }
  if (!UUID.test(params.clipId)) return badRequest('잘못된 clip id');
  let body: Record<string, unknown>;
  try { body = await req.json() as Record<string, unknown>; }
  catch { return badRequest('본문이 올바르지 않아.'); }
  const selectedSource = body.selectedSource;
  if (selectedSource !== 'consensus' && selectedSource !== 'direct' && selectedSource !== 'new') {
    return badRequest('확정 소스가 올바르지 않아.');
  }
  const expected = body.expectedHeadRevisionId;
  if (expected !== null && (typeof expected !== 'string' || !UUID.test(expected))) {
    return badRequest('현재 head revision id가 올바르지 않아.');
  }
  const reason = typeof body.reason === 'string' ? body.reason.trim() : '';
  if (reason.length < 10 || reason.length > 500) return badRequest('사유는 10~500자여야 해.');

  try {
    let newGt: GroundTruthInput | null = null;
    if (selectedSource === 'new') {
      const { data: clips, error: clipError } = await supabaseAdmin.from('motion_clips')
        .select('duration_sec').eq('id', params.clipId).limit(1);
      if (clipError) throw clipError;
      const clip = (clips ?? [])[0] as { duration_sec: number } | undefined;
      if (!clip) return NextResponse.json({ detail: '대상을 찾을 수 없어.', code: 'not_found' }, { status: 404 });
      try { newGt = validateGroundTruth(body.gt, Number(clip.duration_sec) || 60); }
      catch (cause) {
        if (cause instanceof GroundTruthValidationError) {
          return NextResponse.json({ detail: cause.message, issues: cause.issues }, { status: 400 });
        }
        return badRequest((cause as Error).message);
      }
    }
    const { data, error } = await supabaseAdmin.rpc('fn_resolve_motion_clip_gt_reconciliation', {
      p_clip_id: params.clipId, p_actor_id: owner.userId,
      p_expected_head_revision_id: expected ?? null,
      p_selected_source: selectedSource, p_new_gt: newGt, p_reason: reason,
    });
    if (error) return motionRpcErrorResponse(error) ?? motionLabelingDatabaseError(error);
    return NextResponse.json({ ok: true, revisionId: (data as { revision_id?: string })?.revision_id ?? null });
  } catch (cause) {
    return motionLabelingDatabaseError(cause);
  }
}
