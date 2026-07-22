import { NextRequest, NextResponse } from 'next/server';

import { requireOwner } from '@/lib/labelingAccess';
import {
  motionLabelingDatabaseError,
  motionRpcErrorResponse,
} from '@/lib/labelingV3Server';
import { supabaseAdmin } from '@/lib/supabase';

export const runtime = 'nodejs';

// POST /api/labeling-v3/[clipId]/decision — owner 팀 큐 분류(설계 §5.3·§7.5).
//
// label|hold|skip|reset. owner 전용(requireOwner). actor 는 body 가 아니라 bearer 에서 온다.
// optimistic concurrency(expected_updated_at)로 stale 탭 차단, 세션 있는 clip skip 은 거부.
// 경합/무결성은 fn_decide_motion_clip_labeling RPC 가 DB 에서 강제하고, 안정 SQLSTATE 만
// 공개 상태코드로 매핑한다(원문 미노출).

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const DECISIONS = new Set(['label', 'hold', 'skip', 'reset']);

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

  const decision = body.decision;
  if (typeof decision !== 'string' || !DECISIONS.has(decision)) {
    return badRequest('잘못된 decision');
  }

  // note: 선택. 있으면 trim 후 10~500. reset 에는 note 를 넘기지 않는다(무의미).
  let note: string | null = null;
  if (decision !== 'reset' && body.note != null) {
    if (typeof body.note !== 'string') return badRequest('잘못된 note');
    const trimmed = body.note.trim();
    if (trimmed.length < 10 || trimmed.length > 500) return badRequest('note 는 10~500자여야 해.');
    note = trimmed;
  }

  // expected_updated_at: optimistic concurrency 기준값. 있으면 유효 timestamp 여야 한다.
  let expectedUpdatedAt: string | null = null;
  if (body.expected_updated_at != null) {
    if (
      typeof body.expected_updated_at !== 'string' ||
      Number.isNaN(Date.parse(body.expected_updated_at))
    ) {
      return badRequest('잘못된 expected_updated_at');
    }
    expectedUpdatedAt = body.expected_updated_at;
  }

  try {
    const { data, error } = await supabaseAdmin.rpc('fn_decide_motion_clip_labeling', {
      p_clip_id: params.clipId,
      p_actor_id: owner.userId,
      p_decision: decision,
      p_expected_updated_at: expectedUpdatedAt,
      p_note: note,
    });
    if (error) return motionRpcErrorResponse(error) ?? motionLabelingDatabaseError(error);

    // RETURNS 단일 composite → data 는 row 객체(방어적으로 배열도 처리). owner uuid(decided_by)는 제외.
    const row = (Array.isArray(data) ? data[0] : data) as {
      clip_id: string;
      owner_decision: string | null;
      decided_at: string | null;
      decision_note: string | null;
      updated_at: string;
    };
    return NextResponse.json({
      clip_id: row.clip_id,
      state: row.owner_decision ?? 'unreviewed',
      decided_at: row.decided_at,
      note: row.decision_note,
      updated_at: row.updated_at,
    });
  } catch (cause) {
    return motionLabelingDatabaseError(cause);
  }
}
