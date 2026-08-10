import { NextRequest, NextResponse } from 'next/server';

import { databaseUnavailable } from '@/lib/apiErrors';
import { requireLabelingAccess } from '@/lib/labelingAccess';
import { supabaseAdmin } from '@/lib/supabase';
import { isYoloUuid, mapRevealResult } from '@/lib/yoloContribution';
import { yoloContributionRpcError } from '@/lib/yoloContributionServer';

export const runtime = 'nodejs';

export async function POST(req: NextRequest, { params }: { params: { taskId: string } }) {
  const access = await requireLabelingAccess(req);
  if (!access.ok) return access.response;
  if (!isYoloUuid(params.taskId)) return NextResponse.json({ detail: '작업 번호가 올바르지 않아.' }, { status: 400 });
  try {
    const { data, error } = await supabaseAdmin.rpc('fn_reveal_yolo_bbox_prediction', {
      p_contributor_id: access.userId,
      p_task_id: params.taskId,
    });
    if (error) return yoloContributionRpcError(error) ?? databaseUnavailable('yolo reveal', error);
    return NextResponse.json(mapRevealResult(data));
  } catch (cause) {
    return databaseUnavailable('yolo reveal', cause);
  }
}
