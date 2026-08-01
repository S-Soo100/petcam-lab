import { NextRequest, NextResponse } from 'next/server';

import { databaseUnavailable } from '@/lib/apiErrors';
import { requireOwner } from '@/lib/labelingAccess';
import {
  boundaryRpcErrorResponse,
  isBoundaryEligibilityDecision,
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
  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ detail: '요청 형식이 올바르지 않아.' }, { status: 400 });
  }
  const decision = (body as { decision?: unknown } | null)?.decision;
  if (!isBoundaryEligibilityDecision(decision)) {
    return NextResponse.json({ detail: '영상 자격 판정을 하나 골라줘.' }, { status: 400 });
  }
  try {
    const { data, error } = await supabaseAdmin.rpc('fn_submit_rba_boundary_eligibility', {
      p_owner_id: access.userId,
      p_pair_id: params.pairId,
      p_decision: decision,
    });
    if (error) {
      return boundaryRpcErrorResponse(error) ?? databaseUnavailable('rba boundary eligibility', error);
    }
    return NextResponse.json(data);
  } catch (cause) {
    return databaseUnavailable('rba boundary eligibility', cause);
  }
}
