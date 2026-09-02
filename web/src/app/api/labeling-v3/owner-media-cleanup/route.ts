import { NextRequest, NextResponse } from 'next/server';

import { requireOwner } from '@/lib/labelingAccess';
import { motionLabelingDatabaseError, motionRpcErrorResponse } from '@/lib/labelingV3Server';
import { mapOwnerCleanupRow, mapOwnerCleanupSummary } from '@/lib/rbaOwnerMediaCleanup';
import { supabaseAdmin } from '@/lib/supabase';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(req: NextRequest) {
  const owner = await requireOwner(req);
  if (!owner.ok) return owner.response;
  try {
    const summaryResult = await supabaseAdmin.rpc(
      'fn_get_rba_owner_media_cleanup_summary_v1',
      { p_owner_id: owner.userId },
    );
    if (summaryResult.error) {
      return motionRpcErrorResponse(summaryResult.error) ?? motionLabelingDatabaseError(summaryResult.error);
    }
    const listResult = await supabaseAdmin.rpc('fn_list_rba_owner_media_cleanup_v1', {
      p_owner_id: owner.userId,
      p_cursor_started_at: null,
      p_cursor_clip_id: null,
      p_limit: 1,
    });
    if (listResult.error) {
      return motionRpcErrorResponse(listResult.error) ?? motionLabelingDatabaseError(listResult.error);
    }
    const row = ((listResult.data ?? []) as Record<string, unknown>[])[0];
    return NextResponse.json({
      item: row ? mapOwnerCleanupRow(row) : null,
      summary: mapOwnerCleanupSummary((summaryResult.data as Record<string, unknown> | null) ?? null),
    });
  } catch (cause) {
    return motionLabelingDatabaseError(cause);
  }
}
