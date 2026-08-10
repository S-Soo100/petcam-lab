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
  if (!annotation) return NextResponse.json({ detail: '게코 박스를 다시 확인해.' }, { status: 400 });
  try {
    const { error } = await supabaseAdmin.rpc('fn_submit_yolo_bbox_blind', {
      p_contributor_id: access.userId,
      p_task_id: params.taskId,
      p_boxes: annotation.boxes,
      p_no_gecko: annotation.no_gecko,
    });
    if (error) return yoloContributionRpcError(error) ?? databaseUnavailable('yolo blind submit', error);
    return NextResponse.json({ task_id: params.taskId, stage: 'submitted' });
  } catch (cause) {
    return databaseUnavailable('yolo blind submit', cause);
  }
}
