import 'server-only';

import { mapHighlightCurrentRow, mapHighlightInitialRow, type HighlightCurrentRow, type HighlightInitialRow } from '@/lib/highlightV4Server';
import type { HighlightDetail } from '@/lib/highlightV4';
import { readGmeActiveContract } from '@/lib/labelingV3Server';
import { supabaseAdmin } from '@/lib/supabase';
import { reviewerDisplayName } from './_access';

export class HighlightRpcError extends Error {
  constructor(public readonly cause: unknown) { super('highlight_rpc_error'); }
}

// 현재값 + 1차 판정. RPC 오류는 HighlightRpcError 로 감싸 route 가 highlightRpcErrorResponse 로 매핑한다.
export async function loadHighlightDetail(clipId: string): Promise<HighlightDetail> {
  const contract = readGmeActiveContract();
  const args = { p_clip_id: clipId, p_engine_schema_version: contract.engine_schema_version, p_algorithm_version: contract.algorithm_version, p_detector_identity: contract.detector_identity };
  const current = await supabaseAdmin.rpc('fn_highlight_current', args);
  if (current.error) throw new HighlightRpcError(current.error);
  const initial = await supabaseAdmin.rpc('fn_highlight_initial', args);
  if (initial.error) throw new HighlightRpcError(initial.error);
  if (!Array.isArray(current.data) || current.data.length !== 1 || !Array.isArray(initial.data) || initial.data.length !== 1) throw new Error('invalid_highlight_result_count');
  const currentRow = current.data[0] as HighlightCurrentRow;
  const name = await reviewerDisplayName(typeof currentRow.reviewer_id === 'string' ? currentRow.reviewer_id : null);
  return { current: mapHighlightCurrentRow(currentRow, name), initial: mapHighlightInitialRow(initial.data[0] as HighlightInitialRow) };
}
