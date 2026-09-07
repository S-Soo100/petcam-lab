import { NextRequest, NextResponse } from 'next/server';

import {
  highlightDatabaseError,
  highlightRpcErrorResponse,
  mapHighlightCurrentRow,
  mapHighlightInitialRow,
  type HighlightCurrentRow,
  type HighlightInitialRow,
} from '@/lib/highlightV4Server';
import { readGmeActiveContract } from '@/lib/labelingV3Server';
import { supabaseAdmin } from '@/lib/supabase';
import { loadV4ClipAccess, reviewerDisplayName } from '../../../_access';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

// GET /api/labeling-v4/clips/[clipId]/highlight — 현재값(사람 확정 우선) + 1차 판정 상세.
// 1차 판정은 저장된 값이 아니라 DB 함수가 지금 계산한 값이다(스펙 §4.2).
export async function GET(req: NextRequest, { params }: { params: { clipId: string } }) {
  try {
    const access = await loadV4ClipAccess(req, params.clipId);
    if (!access.ok) return access.response;

    const contract = readGmeActiveContract();
    const args = {
      p_clip_id: params.clipId,
      p_engine_schema_version: contract.engine_schema_version,
      p_algorithm_version: contract.algorithm_version,
      p_detector_identity: contract.detector_identity,
    };
    const current = await supabaseAdmin.rpc('fn_highlight_current', args);
    if (current.error) return highlightRpcErrorResponse(current.error) ?? highlightDatabaseError(current.error);
    const initial = await supabaseAdmin.rpc('fn_highlight_initial', args);
    if (initial.error) return highlightRpcErrorResponse(initial.error) ?? highlightDatabaseError(initial.error);
    if (!Array.isArray(current.data) || current.data.length !== 1 || !Array.isArray(initial.data) || initial.data.length !== 1) {
      throw new Error('invalid_highlight_result_count');
    }
    const currentRow = current.data[0] as HighlightCurrentRow;
    const name = await reviewerDisplayName(typeof currentRow.reviewer_id === 'string' ? currentRow.reviewer_id : null);
    return NextResponse.json({
      current: mapHighlightCurrentRow(currentRow, name),
      initial: mapHighlightInitialRow(initial.data[0] as HighlightInitialRow),
    });
  } catch (cause) {
    return highlightDatabaseError(cause);
  }
}
