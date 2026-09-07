import { NextRequest, NextResponse } from 'next/server';

import { highlightDatabaseError } from '@/lib/highlightV4Server';
import { requireOwner } from '@/lib/labelingAccess';
import { readGmeActiveContract } from '@/lib/labelingV3Server';
import { supabaseAdmin } from '@/lib/supabase';
import { resolveReviewerName } from '../../_access';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

interface OverviewMemberRow { user_id?: unknown; display_name?: unknown; labeled_7d?: unknown }

// GET /api/labeling-v4/owner/overview — RPC 의 jsonb 집계. members 표시명만 단일 resolver 로 해석한다
// (SQL 은 raw display_name). owner 전용 화면이라 user_id 는 그대로 싣는다.
export async function GET(req: NextRequest) {
  const owner = await requireOwner(req);
  if (!owner.ok) return owner.response;
  try {
    const c = readGmeActiveContract();
    const { data, error } = await supabaseAdmin.rpc('fn_get_labeling_v4_overview', { p_engine_schema_version: c.engine_schema_version, p_algorithm_version: c.algorithm_version, p_detector_identity: c.detector_identity });
    if (error) throw error;
    const overview = (data ?? {}) as { members?: unknown };
    const members = (Array.isArray(overview.members) ? overview.members : []).flatMap((m: OverviewMemberRow) => {
      if (typeof m.user_id !== 'string') return [];
      return [{
        user_id: m.user_id,
        display_name: resolveReviewerName({ reviewerId: m.user_id, displayName: typeof m.display_name === 'string' ? m.display_name : null }),
        labeled_7d: Number(m.labeled_7d ?? 0),
      }];
    });
    return NextResponse.json({ ...overview, members });
  } catch (cause) {
    return highlightDatabaseError(cause);
  }
}
