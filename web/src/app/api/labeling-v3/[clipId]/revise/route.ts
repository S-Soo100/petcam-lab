import { NextRequest, NextResponse } from 'next/server';

import { requireOwner } from '@/lib/labelingAccess';
import { GroundTruthValidationError, validateGroundTruth, type GroundTruthInput } from '@/lib/labelingV2';
import {
  motionLabelingDatabaseError,
  motionRpcErrorResponse,
} from '@/lib/labelingV3Server';
import { supabaseAdmin } from '@/lib/supabase';

export const runtime = 'nodejs';

// POST /api/labeling-v3/[clipId]/revise — owner GT 보정(설계 §7.4).
//
// owner 전용. completed 세션의 current_gt 만 사유와 함께 바꾼다. initial_gt 는 DB 트리거가 보호.
// v2 와 달리 자동 라벨 mirror 를 하지 않는다(설계 §11). GT 는 화이트리스트로 주입 차단.

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function badRequest(detail: string) {
  return NextResponse.json({ detail, code: 'invalid_request' }, { status: 400 });
}

function sanitizeGroundTruth(gt: GroundTruthInput): GroundTruthInput {
  return {
    visibility: gt.visibility,
    primary_action: gt.primary_action,
    observed_actions: gt.observed_actions,
    segments: gt.segments,
    target: gt.target,
    human_confidence: gt.human_confidence,
    context_tags: gt.context_tags,
    activity_intensity: gt.activity_intensity,
    highlight_recommendation: gt.highlight_recommendation,
    enrichment_object: gt.enrichment_object,
    interaction_types: gt.interaction_types,
    note: gt.note,
  };
}

export async function POST(req: NextRequest, { params }: { params: { clipId: string } }) {
  const owner = await requireOwner(req);
  if (!owner.ok) return owner.response;
  if (!UUID.test(params.clipId)) return badRequest('잘못된 clip id');

  let body: Record<string, unknown>;
  try {
    body = (await req.json()) as Record<string, unknown>;
  } catch {
    return badRequest('본문이 올바르지 않아.');
  }

  const reason = typeof body.reason === 'string' ? body.reason.trim() : '';
  if (reason.length < 10 || reason.length > 500) return badRequest('사유는 10~500자여야 해.');

  try {
    const { data: clipData, error: clipErr } = await supabaseAdmin
      .from('motion_clips')
      .select('duration_sec')
      .eq('id', params.clipId)
      .limit(1);
    if (clipErr) throw clipErr;
    const clip = (clipData ?? [])[0] as { duration_sec: number } | undefined;
    if (!clip) return NextResponse.json({ detail: '대상을 찾을 수 없어.', code: 'not_found' }, { status: 404 });

    let gt: GroundTruthInput;
    try {
      gt = validateGroundTruth(body.gt, Number(clip.duration_sec) || 60);
    } catch (error) {
      if (error instanceof GroundTruthValidationError) {
        return NextResponse.json({ detail: error.message, issues: error.issues }, { status: 400 });
      }
      return badRequest((error as Error).message);
    }

    const { data, error } = await supabaseAdmin.rpc('fn_revise_motion_clip_gt', {
      p_clip_id: params.clipId,
      p_actor_id: owner.userId,
      p_new_gt: sanitizeGroundTruth(gt),
      p_reason: reason,
    });
    if (error) return motionRpcErrorResponse(error) ?? motionLabelingDatabaseError(error);

    const session = (Array.isArray(data) ? data[0] : data) as { stage: string; current_gt: unknown };
    return NextResponse.json({ ok: true, stage: session.stage });
  } catch (cause) {
    return motionLabelingDatabaseError(cause);
  }
}
