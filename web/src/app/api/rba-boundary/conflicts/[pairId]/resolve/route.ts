import { NextRequest, NextResponse } from 'next/server';

import { databaseUnavailable } from '@/lib/apiErrors';
import { requireOwner } from '@/lib/labelingAccess';
import {
  boundaryRpcErrorResponse,
  isBoundaryDecision,
  isBoundaryUuid,
} from '@/lib/rbaBoundaryServer';
import { supabaseAdmin } from '@/lib/supabase';

export const runtime = 'nodejs';

export async function POST(
  req: NextRequest,
  { params }: { params: { pairId: string } },
) {
  const access = await requireOwner(req);
  if (!access.ok) return access.response;
  if (!isBoundaryUuid(params.pairId)) {
    return NextResponse.json({ detail: '문제 번호가 올바르지 않아.' }, { status: 400 });
  }
  let body: { final_decision?: unknown; reason?: unknown };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ detail: '요청 형식이 올바르지 않아.' }, { status: 400 });
  }
  const reason = typeof body.reason === 'string' ? body.reason.trim() : '';
  if (!isBoundaryDecision(body.final_decision) || reason.length < 3 || reason.length > 1000) {
    return NextResponse.json(
      { detail: '최종 판정과 세 글자 이상의 이유를 적어줘.' },
      { status: 400 },
    );
  }
  try {
    const { data, error } = await supabaseAdmin.rpc('fn_resolve_rba_boundary_conflict', {
      p_owner_id: access.userId,
      p_pair_id: params.pairId,
      p_final_decision: body.final_decision,
      p_reason: reason,
    });
    if (error) {
      return boundaryRpcErrorResponse(error) ?? databaseUnavailable('rba boundary resolve', error);
    }
    return NextResponse.json(data);
  } catch (cause) {
    return databaseUnavailable('rba boundary resolve', cause);
  }
}
