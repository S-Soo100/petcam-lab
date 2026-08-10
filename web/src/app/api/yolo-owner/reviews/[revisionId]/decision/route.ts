import { NextRequest, NextResponse } from 'next/server';

import { databaseUnavailable } from '@/lib/apiErrors';
import { requireOwner } from '@/lib/labelingAccess';
import { supabaseAdmin } from '@/lib/supabase';
import { isYoloUuid } from '@/lib/yoloContribution';
import { yoloContributionRpcError } from '@/lib/yoloContributionServer';

export const runtime = 'nodejs';

export async function POST(req: NextRequest, { params }: { params: { revisionId: string } }) {
  const access = await requireOwner(req);
  if (!access.ok) return access.response;
  if (!isYoloUuid(params.revisionId)) return NextResponse.json({ detail: 'revision 번호가 올바르지 않아.' }, { status: 400 });
  let body: Record<string, unknown>;
  try { const value: unknown = await req.json(); body = typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {}; } catch { return NextResponse.json({ detail: '요청 형식이 올바르지 않아.' }, { status: 400 }); }
  const decision = body.decision;
  const reason = typeof body.reason === 'string' ? body.reason.trim() : '';
  const dataset = typeof body.dataset_version_id === 'string' ? body.dataset_version_id : null;
  if ((decision !== 'approve' && decision !== 'reject') || reason.length < 3 || reason.length > 1000 || (decision === 'approve' && (!dataset || !isYoloUuid(dataset)))) {
    return NextResponse.json({ detail: 'Owner 판정, 사유, Dataset version을 확인해.' }, { status: 400 });
  }
  try {
    const { error } = await supabaseAdmin.rpc('fn_owner_decide_yolo_bbox_revision', {
      p_owner_id: access.userId, p_revision_id: params.revisionId, p_decision: decision,
      p_reason: reason, p_dataset_version_id: decision === 'approve' ? dataset : null,
    });
    if (error) return yoloContributionRpcError(error) ?? databaseUnavailable('yolo owner decision', error);
    return NextResponse.json({ revision_id: params.revisionId, decision });
  } catch (cause) {
    return databaseUnavailable('yolo owner decision', cause);
  }
}
