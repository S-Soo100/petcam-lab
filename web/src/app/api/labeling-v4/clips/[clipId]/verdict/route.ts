import { NextRequest, NextResponse } from 'next/server';

import { isHighlightChangeReason, type HighlightVerdictResult } from '@/lib/highlightV4';
import { highlightDatabaseError, highlightRpcErrorResponse } from '@/lib/highlightV4Server';
import { readGmeActiveContract } from '@/lib/labelingV3Server';
import { supabaseAdmin } from '@/lib/supabase';
import { loadV4ClipAccess } from '../../../_access';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

function badRequest(detail: string) {
  return NextResponse.json({ detail, code: 'invalid_request' }, { status: 400 });
}

// POST /api/labeling-v4/clips/[clipId]/verdict — 사람 확정 append(v4 스펙 §4.2 낙관적 잠금).
export async function POST(req: NextRequest, { params }: { params: { clipId: string } }) {
  try {
    const access = await loadV4ClipAccess(req, params.clipId);
    if (!access.ok) return access.response;

    let body: { verdict?: unknown; change_reason?: unknown; kind?: unknown };
    try { body = await req.json(); } catch { return badRequest('JSON 본문이 필요해.'); }
    if (typeof body.verdict !== 'boolean') return badRequest('verdict 는 true/false 여야 해.');
    const reason = body.change_reason ?? null;
    if (reason !== null && !isHighlightChangeReason(reason)) return badRequest('change_reason 값이 잘못됐어.');
    const kind = body.kind ?? 'initial';
    if (kind !== 'initial' && kind !== 'correction') return badRequest('kind 값이 잘못됐어.');
    if (kind === 'correction' && !access.isOwner) {
      return NextResponse.json({ detail: '정정은 owner 만 할 수 있어.', code: 'forbidden' }, { status: 403 });
    }

    const contract = readGmeActiveContract();
    const { data, error } = await supabaseAdmin.rpc('fn_submit_highlight_verdict', {
      p_clip_id: params.clipId,
      p_reviewer_id: access.userId,
      p_is_owner: access.isOwner,
      p_verdict: body.verdict,
      p_kind: kind,
      p_change_reason: reason,
      p_engine_schema_version: contract.engine_schema_version,
      p_algorithm_version: contract.algorithm_version,
      p_detector_identity: contract.detector_identity,
    });
    if (error) return highlightRpcErrorResponse(error) ?? highlightDatabaseError(error);
    if (!Array.isArray(data) || data.length !== 1) throw new Error('invalid_verdict_result_count');
    const row = data[0] as HighlightVerdictResult;
    return NextResponse.json({ verdict_id: row.verdict_id, initial: row.initial, changed: row.changed, rule_version: row.rule_version });
  } catch (cause) {
    return highlightDatabaseError(cause);
  }
}
