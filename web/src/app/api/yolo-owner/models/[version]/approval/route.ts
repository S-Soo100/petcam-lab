import { NextRequest, NextResponse } from 'next/server';

import { databaseUnavailable } from '@/lib/apiErrors';
import { requireOwner } from '@/lib/labelingAccess';
import { supabaseAdmin } from '@/lib/supabase';
import { yoloContributionRpcError } from '@/lib/yoloContributionServer';

export const runtime = 'nodejs';
const VERSION = /^[A-Za-z0-9._-]{1,128}$/;

export async function POST(req: NextRequest, { params }: { params: { version: string } }) {
  const access = await requireOwner(req);
  if (!access.ok) return access.response;
  if (!VERSION.test(params.version)) {
    return NextResponse.json({ detail: 'model version이 올바르지 않아.' }, { status: 400 });
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
  const decision = body.decision;
  const reason = typeof body.reason === 'string' ? body.reason.trim() : '';
  if ((decision !== 'approve' && decision !== 'reject') || reason.length < 3 || reason.length > 1000) {
    return NextResponse.json({ detail: '모델 판정과 사유를 확인해.' }, { status: 400 });
  }
  try {
    const { data, error } = await supabaseAdmin.rpc('fn_owner_decide_yolo_model', {
      p_owner_id: access.userId,
      p_model_version: params.version,
      p_decision: decision,
      p_reason: reason,
    });
    if (error) return yoloContributionRpcError(error) ?? databaseUnavailable('yolo model approval', error);
    return NextResponse.json(data);
  } catch (cause) {
    return databaseUnavailable('yolo model approval', cause);
  }
}
