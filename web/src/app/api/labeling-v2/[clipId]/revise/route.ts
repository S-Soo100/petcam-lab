import { NextRequest, NextResponse } from 'next/server';

import { databaseUnavailable } from '@/lib/apiErrors';
import { requireOwner } from '@/lib/labelingAccess';
import {
  GroundTruthValidationError,
  validateGroundTruth,
  validateVlmReview,
} from '@/lib/labelingV2';
import { supabaseAdmin } from '@/lib/supabase';
import { mapLickTarget } from '../../_helpers';

export const runtime = 'nodejs';

// POST /api/labeling-v2/[clipId]/revise — owner 전용 현재 GT 보정(설계 §7).
//
// 순서(§7.3): bearer 인증 → owner 확인 → body 검증 → 공통 GT/VLM validator → 원자적 RPC.
// initial_gt·prediction_snapshot·gt_locked_at·completed_at 은 절대 바꾸지 않고, current_gt 와
// VLM review 만 사유와 함께 보정하며 append-only revision 을 남긴다.
// 대상 session 은 서버가 URL clipId + bearer owner 로 결정한다(body 의 session/clip/revised_by 불신).
export async function POST(
  req: NextRequest,
  { params }: { params: { clipId: string } },
) {
  // 무인증 401 / 비owner 403 / env 누락 503.
  const owner = await requireOwner(req);
  if (!owner.ok) return owner.response;
  const { userId } = owner;

  let body: { gt?: unknown; vlm_review?: unknown; reason?: unknown };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ detail: '요청 본문을 읽지 못했어.' }, { status: 400 });
  }

  // 보정 사유 10~500자 필수(§7.1). 화면에 표시될 수 있으니 비밀값 금지 안내는 UI 에.
  const reason = typeof body.reason === 'string' ? body.reason.trim() : '';
  if (reason.length < 10 || reason.length > 500) {
    return NextResponse.json(
      { detail: '보정 사유는 10~500자로 적어줘.' },
      { status: 400 },
    );
  }

  // GT segment 범위 검증(0≤start<end≤duration)에 clip 길이가 필요하다. 60초 fallback 을 쓰면
  // 잘못된 duration 으로 segment 가 통과·저장될 수 있으므로, 조회 오류/부재/무효 duration 을
  // 각각 명확히 끊는다: DB 오류 → 내부 메시지 숨긴 502, clip 없음 → 404, duration 무효 → 502.
  let clipLookup;
  try {
    clipLookup = await supabaseAdmin
      .from('camera_clips')
      .select('duration_sec')
      .eq('id', params.clipId)
      .limit(1);
  } catch (error) {
    return databaseUnavailable('labeling revise clip lookup', error);
  }
  if (clipLookup.error) {
    return databaseUnavailable('labeling revise clip lookup', clipLookup.error);
  }
  const clipRow = (clipLookup.data ?? [])[0];
  if (!clipRow) {
    return NextResponse.json({ detail: 'not found' }, { status: 404 });
  }
  const duration = Number(clipRow.duration_sec);
  if (!Number.isFinite(duration) || duration <= 0) {
    return databaseUnavailable(
      'labeling revise clip duration',
      new Error('camera_clips.duration_sec is missing or invalid'),
    );
  }

  let gt;
  let review;
  try {
    gt = validateGroundTruth(body.gt, duration);
    review = validateVlmReview(body.vlm_review);
  } catch (error) {
    if (error instanceof GroundTruthValidationError) {
      return NextResponse.json(
        { detail: error.message, issues: error.issues },
        { status: 400 },
      );
    }
    return NextResponse.json({ detail: (error as Error).message }, { status: 400 });
  }

  try {
    const { data, error } = await supabaseAdmin.rpc('fn_revise_clip_labeling_session', {
      p_clip_id: params.clipId,
      p_revised_by: userId,
      p_revised_gt: gt,
      p_vlm_verdict: review.verdict,
      p_vlm_error_tags: review.error_tags,
      p_vlm_review_note: review.note,
      p_reason: reason,
      p_action: gt.primary_action,
      p_lick_target: mapLickTarget(gt.primary_action, gt.target),
      p_behavior_note: gt.note,
    });
    if (error) {
      // 대상 세션 없음/미완료/다른 reviewer → 404. 잘못된 인자 → 400. 그 외 → 내부 메시지 숨긴 502.
      if (error.code === 'P0002') {
        return NextResponse.json({ detail: 'not found' }, { status: 404 });
      }
      if (error.code === '22023') {
        return NextResponse.json({ detail: '보정 입력이 올바르지 않아.' }, { status: 400 });
      }
      return databaseUnavailable('labeling revise', error);
    }
    const session = Array.isArray(data) ? data[0] : data;
    return NextResponse.json({ session, revised_at: session?.updated_at ?? null });
  } catch (error) {
    return databaseUnavailable('labeling revise', error);
  }
}
