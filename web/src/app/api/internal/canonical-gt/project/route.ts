import { randomUUID } from 'node:crypto';

import { NextRequest, NextResponse } from 'next/server';

import { databaseUnavailable } from '@/lib/apiErrors';
import { supabaseAdmin } from '@/lib/supabase';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const PROJECT_RPC = 'fn_project_motion_clip_canonical_gt';
const RECORD_RPC = 'fn_record_motion_clip_gt_projection_run';

function hidden() {
  return NextResponse.json({ detail: 'not found' }, { status: 404 });
}

async function recordRun(input: {
  runId: string;
  status: 'succeeded' | 'failed';
  startedAt: string;
  scanned?: number;
  inserted?: number;
  errorCode?: string;
}) {
  return supabaseAdmin.rpc(RECORD_RPC, {
    p_run_id: input.runId,
    p_status: input.status,
    p_scanned: input.scanned ?? 0,
    p_inserted: input.inserted ?? 0,
    p_error_code: input.errorCode ?? null,
    p_started_at: input.startedAt,
  });
}

// Vercel Cron 전용 entrypoint. blind submit/finalize route와 호출 관계가 없어서
// projection 실패가 현재 교차검수 transaction을 막지 않는다.
export async function GET(req: NextRequest) {
  const secret = process.env.CRON_SECRET;
  if (!secret || req.headers.get('authorization') !== `Bearer ${secret}`) return hidden();
  if (process.env.LABELING_CANONICAL_GT_PROJECTION_ENABLED !== 'true') return hidden();

  const ownerId = process.env.DEV_USER_ID;
  if (!ownerId) {
    return NextResponse.json({ detail: 'projection unavailable' }, { status: 503 });
  }

  const runId = randomUUID();
  const startedAt = new Date().toISOString();
  try {
    const { data, error } = await supabaseAdmin.rpc(PROJECT_RPC, {
      p_owner_id: ownerId,
      p_apply: true,
      p_limit: 500,
      p_after_source_id: null,
      p_projection_run_id: runId,
    });
    if (error) {
      await recordRun({
        runId,
        status: 'failed',
        startedAt,
        errorCode: 'projection_rpc_failed',
      });
      return databaseUnavailable('canonical gt projection', error);
    }
    const result = (data ?? {}) as Record<string, unknown>;
    const scanned = Number(result.scanned);
    const inserted = Number(result.inserted);
    if (!Number.isInteger(scanned) || scanned < 0 || !Number.isInteger(inserted) || inserted < 0) {
      await recordRun({
        runId,
        status: 'failed',
        startedAt,
        errorCode: 'projection_response_invalid',
      });
      return NextResponse.json({ detail: 'projection unavailable' }, { status: 502 });
    }
    const recorded = await recordRun({
      runId,
      status: 'succeeded',
      startedAt,
      scanned,
      inserted,
    });
    if (recorded.error) return databaseUnavailable('canonical gt projection run', recorded.error);
    return NextResponse.json({
      ok: true,
      run_id: runId,
      result: {
        scanned,
        inserted,
        already_present: Number(result.already_present) || 0,
        conflicts: Number(result.conflicts) || 0,
      },
    });
  } catch (cause) {
    return databaseUnavailable('canonical gt projection', cause);
  }
}
