import { NextRequest, NextResponse } from 'next/server';

import { databaseUnavailable } from '@/lib/apiErrors';
import { requireOwner } from '@/lib/labelingAccess';
import { supabaseAdmin } from '@/lib/supabase';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(req: NextRequest) {
  const owner = await requireOwner(req);
  if (!owner.ok) return owner.response;
  if (process.env.LABELING_CANONICAL_GT_PROJECTION_ENABLED !== 'true') {
    return NextResponse.json({ detail: 'not found' }, { status: 404 });
  }

  try {
    const { data, error } = await supabaseAdmin.rpc(
      'fn_get_motion_clip_gt_projection_health',
    );
    if (error) return databaseUnavailable('canonical gt health', error);
    const row = (data ?? {}) as Record<string, unknown>;
    return NextResponse.json({
      healthy: row.healthy === true,
      lastSuccessAt:
        typeof row.last_success_at === 'string' ? row.last_success_at : null,
      lagSeconds: Number.isFinite(Number(row.lag_seconds))
        ? Number(row.lag_seconds)
        : null,
      pendingFinalSourceCount: Number.isFinite(Number(row.pending_final_source_count))
        ? Number(row.pending_final_source_count)
        : 0,
      lastErrorCode:
        typeof row.last_error_code === 'string' ? row.last_error_code : null,
    });
  } catch (cause) {
    return databaseUnavailable('canonical gt health', cause);
  }
}
