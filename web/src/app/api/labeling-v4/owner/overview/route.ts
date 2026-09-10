import { NextRequest, NextResponse } from 'next/server';

import { highlightDatabaseError } from '@/lib/highlightV4Server';
import { requireOwner } from '@/lib/labelingAccess';
import { readGmeActiveContract } from '@/lib/labelingV3Server';
import { supabaseAdmin } from '@/lib/supabase';
import { resolveReviewerName } from '../../_access';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

interface OverviewMemberRow { user_id?: unknown; display_name?: unknown; labeled_7d?: unknown }

// 활성 계약 커버리지(2.6.1 전환 준비). RPC 실패는 null 로 접어 현황 자체는 계속 뜨게 한다.
async function loadCoverage(c: { engine_schema_version: string; algorithm_version: string; detector_identity: string }) {
  try {
    const { data, error } = await supabaseAdmin.rpc('fn_gme_contract_coverage', { p_engine_schema_version: c.engine_schema_version, p_algorithm_version: c.algorithm_version, p_detector_identity: c.detector_identity });
    if (error) throw error;
    const d = (data ?? {}) as Record<string, unknown>;
    const n = (v: unknown) => (typeof v === 'string' ? Number(v) : typeof v === 'number' ? v : 0);
    return { last7d_total: n(d.last7d_total), last7d_with_run: n(d.last7d_with_run), all_total: n(d.all_total), all_with_run: n(d.all_with_run) };
  } catch {
    return null;
  }
}

// GET /api/labeling-v4/owner/overview — RPC 의 jsonb 집계. members 표시명만 단일 resolver 로 해석한다
// (SQL 은 raw display_name). owner 전용 화면이라 user_id 는 그대로 싣는다.
export async function GET(req: NextRequest) {
  const owner = await requireOwner(req);
  if (!owner.ok) return owner.response;
  try {
    const c = readGmeActiveContract();
    const [{ data, error }, coverage] = await Promise.all([
      supabaseAdmin.rpc('fn_get_labeling_v4_overview', { p_engine_schema_version: c.engine_schema_version, p_algorithm_version: c.algorithm_version, p_detector_identity: c.detector_identity }),
      loadCoverage(c),
    ]);
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
    return NextResponse.json({ ...overview, members, coverage });
  } catch (cause) {
    return highlightDatabaseError(cause);
  }
}
