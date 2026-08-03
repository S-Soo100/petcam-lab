import { NextRequest, NextResponse } from 'next/server';

import { mapCanonicalMotionGt } from '@/lib/canonicalMotionGt';
import { requireOwner } from '@/lib/labelingAccess';
import { GroundTruthValidationError, validateGroundTruth, type GroundTruthInput } from '@/lib/labelingV2';
import { motionLabelingDatabaseError, motionRpcErrorResponse } from '@/lib/labelingV3Server';
import { supabaseAdmin } from '@/lib/supabase';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function badRequest(detail: string) {
  return NextResponse.json({ detail, code: 'invalid_request' }, { status: 400 });
}

function sanitizeGroundTruth(gt: GroundTruthInput): GroundTruthInput {
  return {
    visibility: gt.visibility, primary_action: gt.primary_action,
    observed_actions: gt.observed_actions, segments: gt.segments, target: gt.target,
    human_confidence: gt.human_confidence, context_tags: gt.context_tags,
    activity_intensity: gt.activity_intensity,
    highlight_recommendation: gt.highlight_recommendation,
    enrichment_object: gt.enrichment_object, interaction_types: gt.interaction_types,
    note: gt.note,
  };
}

export async function GET(req: NextRequest, { params }: { params: { clipId: string } }) {
  const owner = await requireOwner(req);
  if (!owner.ok) return owner.response;
  if (process.env.LABELING_CANONICAL_GT_OWNER_READ_ENABLED !== 'true') {
    return NextResponse.json({ detail: 'not found' }, { status: 404 });
  }
  if (!UUID.test(params.clipId)) return badRequest('잘못된 clip id');
  try {
    const { data, error } = await supabaseAdmin.rpc('fn_get_motion_clip_canonical_gt', {
      p_clip_id: params.clipId, p_actor_id: owner.userId,
    });
    if (error) return motionRpcErrorResponse(error) ?? motionLabelingDatabaseError(error);
    return NextResponse.json(mapCanonicalMotionGt(data));
  } catch (cause) {
    return motionLabelingDatabaseError(cause);
  }
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
  const expectedRevisionId = typeof body.expectedRevisionId === 'string' ? body.expectedRevisionId : '';
  const reason = typeof body.reason === 'string' ? body.reason.trim() : '';
  if (!UUID.test(expectedRevisionId)) return badRequest('현재 revision id가 필요해.');
  if (reason.length < 10 || reason.length > 500) return badRequest('사유는 10~500자여야 해.');

  try {
    const { data: clipData, error: clipError } = await supabaseAdmin.from('motion_clips')
      .select('duration_sec').eq('id', params.clipId).limit(1);
    if (clipError) throw clipError;
    const clip = (clipData ?? [])[0] as { duration_sec: number } | undefined;
    if (!clip) return NextResponse.json({ detail: '대상을 찾을 수 없어.', code: 'not_found' }, { status: 404 });
    let gt: GroundTruthInput;
    try { gt = validateGroundTruth(body.gt, Number(clip.duration_sec) || 60); }
    catch (cause) {
      if (cause instanceof GroundTruthValidationError) {
        return NextResponse.json({ detail: cause.message, issues: cause.issues }, { status: 400 });
      }
      return badRequest((cause as Error).message);
    }
    const { data, error } = await supabaseAdmin.rpc('fn_override_motion_clip_canonical_gt', {
      p_clip_id: params.clipId, p_actor_id: owner.userId,
      p_expected_revision_id: expectedRevisionId,
      p_new_gt: sanitizeGroundTruth(gt), p_reason: reason,
    });
    if (error) return motionRpcErrorResponse(error) ?? motionLabelingDatabaseError(error);
    return NextResponse.json({ ok: true, revisionId: (data as { revision_id?: string })?.revision_id ?? null });
  } catch (cause) {
    return motionLabelingDatabaseError(cause);
  }
}
