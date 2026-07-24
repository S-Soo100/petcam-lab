import { NextRequest, NextResponse } from 'next/server';

import { requireOwner } from '@/lib/labelingAccess';
import {
  motionLabelingDatabaseError,
  motionRpcErrorResponse,
} from '@/lib/labelingV3Server';
import { supabaseAdmin } from '@/lib/supabase';

export const runtime = 'nodejs';

// POST /api/labeling-v3/system-exclusions/[clipId]/restore — Owner 복구(설계 §6.3).
//
// quarantined 자동 제외를 사람 라벨 흐름으로 되돌린다. requireOwner 전용, actor 는 bearer 에서 온다.
// reason 은 10~500자(DB RPC 도 동일 강제). fn_restore_short_clip_exclusion 이 triage=label 복귀와
// 시스템 원장 restored 를 한 트랜잭션에서 처리한다. PT409/PT428 → 공개 409(원문 미노출),
// 그 외 안정 코드/미지 코드는 motionRpcErrorResponse/일반화된 502.

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

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

  if (typeof body.reason !== 'string') return badRequest('복구 사유를 입력해줘.');
  const reason = body.reason.trim();
  if (reason.length < 10 || reason.length > 500) {
    return badRequest('복구 사유는 10~500자여야 해.');
  }

  try {
    const { error } = await supabaseAdmin.rpc('fn_restore_short_clip_exclusion', {
      p_clip_id: params.clipId,
      p_actor_id: owner.userId,
      p_reason: reason,
      p_now: new Date().toISOString(),
    });
    if (error) return motionRpcErrorResponse(error) ?? motionLabelingDatabaseError(error);
    return NextResponse.json({ ok: true });
  } catch (cause) {
    return motionLabelingDatabaseError(cause);
  }
}
