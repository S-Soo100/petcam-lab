import { NextRequest, NextResponse } from 'next/server';

import { databaseUnavailable } from '@/lib/apiErrors';
import { requireLabelingAccess } from '@/lib/labelingAccess';
import { supabaseAdmin } from '@/lib/supabase';
import { isYoloUuid, parseHumanAnnotation } from '@/lib/yoloContribution';
import { yoloContributionRpcError } from '@/lib/yoloContributionServer';

export const runtime = 'nodejs';

export async function POST(req: NextRequest, { params }: { params: { taskId: string } }) {
  const access = await requireLabelingAccess(req);
  if (!access.ok) return access.response;
  if (!isYoloUuid(params.taskId)) return NextResponse.json({ detail: '작업 번호가 올바르지 않아.' }, { status: 400 });
  let body: unknown;
  try { body = await req.json(); } catch { return NextResponse.json({ detail: '요청 형식이 올바르지 않아.' }, { status: 400 }); }
  const annotation = parseHumanAnnotation(body);
  const reason = typeof body === 'object' && body !== null && 'reason' in body && typeof (body as { reason: unknown }).reason === 'string'
    ? (body as { reason: string }).reason.trim()
    : '';
  if (!annotation || reason.length < 3 || reason.length > 1000) {
    return NextResponse.json({ detail: '최종 사람 박스와 변경 사유를 확인해.' }, { status: 400 });
  }
  try {
    const { error } = await supabaseAdmin.rpc('fn_submit_yolo_bbox_revision', {
      p_contributor_id: access.userId,
      p_task_id: params.taskId,
      p_boxes: annotation.boxes,
      p_no_gecko: annotation.no_gecko,
      p_reason: reason,
    });
    if (error) return yoloContributionRpcError(error) ?? databaseUnavailable('yolo revision', error);
    return NextResponse.json({ task_id: params.taskId, stage: 'owner_review' });
  } catch (cause) {
    return databaseUnavailable('yolo revision', cause);
  }
}
