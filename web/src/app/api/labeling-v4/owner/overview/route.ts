import { NextRequest, NextResponse } from 'next/server';

import { highlightDatabaseError } from '@/lib/highlightV4Server';
import { requireOwner } from '@/lib/labelingAccess';
import { readGmeActiveContract } from '@/lib/labelingV3Server';
import { supabaseAdmin } from '@/lib/supabase';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

// GET /api/labeling-v4/owner/overview — RPC 가 만든 jsonb 를 그대로 돌려준다.
export async function GET(req: NextRequest) {
  const owner = await requireOwner(req);
  if (!owner.ok) return owner.response;
  try {
    const c = readGmeActiveContract();
    const { data, error } = await supabaseAdmin.rpc('fn_get_labeling_v4_overview', { p_engine_schema_version: c.engine_schema_version, p_algorithm_version: c.algorithm_version, p_detector_identity: c.detector_identity });
    if (error) throw error;
    return NextResponse.json(data);
  } catch (cause) {
    return highlightDatabaseError(cause);
  }
}
