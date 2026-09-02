import { NextRequest, NextResponse } from 'next/server';

import { requireOwner } from '@/lib/labelingAccess';
import { motionLabelingDatabaseError, motionRpcErrorResponse } from '@/lib/labelingV3Server';
import type { OwnerCleanupDecision } from '@/lib/rbaOwnerMediaCleanup';
import { supabaseAdmin } from '@/lib/supabase';

export const runtime = 'nodejs';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const DECISIONS = new Set<OwnerCleanupDecision>([
  'keep',
  'delete_gecko_absent',
  'delete_no_activity',
  'uncertain',
]);

function badRequest(detail: string) {
  return NextResponse.json({ detail, code: 'invalid_request' }, { status: 400 });
}
export async function POST(req: NextRequest, { params }: { params: { clipId: string } }) {
  const owner = await requireOwner(req);
  if (!owner.ok) return owner.response;
  if (!UUID.test(params.clipId)) return badRequest('잘못된 clip id');
  let body: Record<string, unknown>;
  try {
    body = (await req.json()) as Record<string, unknown>;
  } catch {
    return badRequest('본문이 올바르지 않아.');
  }
  if (typeof body.decision !== 'string' || !DECISIONS.has(body.decision as OwnerCleanupDecision)) {
    return badRequest('판정 값이 올바르지 않아.');
  }
  try {
    const { error } = await supabaseAdmin.rpc('fn_decide_rba_owner_media_cleanup_v1', {
      p_owner_id: owner.userId,
      p_clip_id: params.clipId,
      p_decision: body.decision,
      p_reason: null,
    });
    if (error) return motionRpcErrorResponse(error) ?? motionLabelingDatabaseError(error);
    return NextResponse.json({ ok: true });
  } catch (cause) {
    return motionLabelingDatabaseError(cause);
  }
}
