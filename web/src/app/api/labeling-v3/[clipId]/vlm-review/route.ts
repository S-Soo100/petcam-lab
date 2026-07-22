import { NextRequest, NextResponse } from 'next/server';

import { requireProductionLabelingAccess } from '@/lib/labelingAccess';
import { validateVlmReview } from '@/lib/labelingV2';
import {
  motionLabelingDatabaseError,
  motionRpcErrorResponse,
} from '@/lib/labelingV3Server';
import { supabaseAdmin } from '@/lib/supabase';

export const runtime = 'nodejs';

// POST /api/labeling-v3/[clipId]/vlm-review — 검수 완료(설계 §7.3).
//
// verdict 있으면 기존 strict validator 로 검증 후 vlm_reviewed 완료.
// verdict 없으면 no_prediction 완료(RPC 가 세션 prediction 유무로 강제 — prediction 있는데
// verdict 없으면 RPC 가 22023 → 400). reviewer 는 bearer 에서 오고, 대상 세션은 (clip, reviewer)
// stage='gt_locked' 로 서버가 찾는다(클라이언트가 세션/reviewer 를 못 넘김).

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function badRequest(detail: string) {
  return NextResponse.json({ detail, code: 'invalid_request' }, { status: 400 });
}

export async function POST(req: NextRequest, { params }: { params: { clipId: string } }) {
  const access = await requireProductionLabelingAccess(req);
  if (!access.ok) return access.response;
  if (!UUID.test(params.clipId)) return badRequest('잘못된 clip id');

  let body: Record<string, unknown>;
  try {
    body = (await req.json()) as Record<string, unknown>;
  } catch {
    return badRequest('본문이 올바르지 않아.');
  }

  let verdict: string | null = null;
  let errorTags: string[] = [];
  let note: string | null = null;

  if (body.verdict != null) {
    // prediction 검수 완료 — verdict + error_tags 를 기존 strict validator 로 검증.
    // note 누락(undefined)은 null 로 정규화한다(validator 는 note 를 null|string 으로만 받음).
    try {
      const review = validateVlmReview({ ...body, note: body.note ?? null });
      verdict = review.verdict;
      errorTags = review.error_tags;
      note = review.note;
    } catch (error) {
      return badRequest((error as Error).message);
    }
  } else {
    // no_prediction 완료 — verdict 없이 note 만 선택.
    if (body.note != null) {
      if (typeof body.note !== 'string') return badRequest('잘못된 note');
      if (body.note.length > 2000) return badRequest('메모는 2000자 이하여야 해.');
      note = body.note;
    }
  }

  try {
    const { data, error } = await supabaseAdmin.rpc('fn_complete_motion_clip_vlm_review', {
      p_clip_id: params.clipId,
      p_reviewer_id: access.userId,
      p_verdict: verdict,
      p_error_tags: errorTags,
      p_review_note: note,
    });
    if (error) return motionRpcErrorResponse(error) ?? motionLabelingDatabaseError(error);

    const session = (Array.isArray(data) ? data[0] : data) as {
      stage: string;
      completion_reason: string | null;
    };
    return NextResponse.json({
      stage: session.stage,
      completion_reason: session.completion_reason,
    });
  } catch (cause) {
    return motionLabelingDatabaseError(cause);
  }
}
