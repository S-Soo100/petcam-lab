import { NextRequest, NextResponse } from 'next/server';

import { databaseUnavailable } from '@/lib/apiErrors';
import { requireOwner } from '@/lib/labelingAccess';
import { supabaseAdmin } from '@/lib/supabase';
import { isYoloUuid } from '@/lib/yoloContribution';
import { yoloContributionRpcError } from '@/lib/yoloContributionServer';

export const runtime = 'nodejs';

export async function POST(req: NextRequest, { params }: { params: { datasetId: string } }) {
  const access = await requireOwner(req);
  if (!access.ok) return access.response;
  if (!isYoloUuid(params.datasetId)) {
    return NextResponse.json({ detail: 'Dataset version이 올바르지 않아.' }, { status: 400 });
  }
  let body: Record<string, unknown>;
  try {
    const value: unknown = await req.json();
    body = typeof value === 'object' && value !== null && !Array.isArray(value)
      ? value as Record<string, unknown>
      : {};
  } catch {
    return NextResponse.json({ detail: '요청 형식이 올바르지 않아.' }, { status: 400 });
  }
  const reason = typeof body.reason === 'string' ? body.reason.trim() : '';
  if (reason.length < 3 || reason.length > 1000) {
    return NextResponse.json({ detail: 'Dataset freeze 사유를 확인해.' }, { status: 400 });
  }
  try {
    const { data, error } = await supabaseAdmin.rpc('fn_freeze_yolo_dataset', {
      p_owner_id: access.userId,
      p_dataset_version_id: params.datasetId,
      p_reason: reason,
    });
    if (error) return yoloContributionRpcError(error) ?? databaseUnavailable('yolo dataset freeze', error);
    return NextResponse.json(data);
  } catch (cause) {
    return databaseUnavailable('yolo dataset freeze', cause);
  }
}
