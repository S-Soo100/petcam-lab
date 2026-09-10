import { NextRequest, NextResponse } from 'next/server';

import { highlightDatabaseError, highlightRpcErrorResponse } from '@/lib/highlightV4Server';
import { requireOwner } from '@/lib/labelingAccess';
import { supabaseAdmin } from '@/lib/supabase';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const DAY_MS = 24 * 3600 * 1000;
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

interface StatsRow {
  rule_version: string; camera_id: string | null; camera_name: string | null;
  verdict_count: number; kept_count: number; decided_count: number; o_to_x: number; x_to_o: number; pending_initial: number;
  reason_counts: Record<string, number>;
}

function parseDate(v: string | null, fallback: Date): Date | null {
  if (v === null) return fallback;
  if (!DATE_RE.test(v)) return null;
  const d = new Date(`${v}T00:00:00.000Z`);
  return Number.isNaN(d.getTime()) ? null : d;
}

// GET ?from=YYYY-MM-DD&to=YYYY-MM-DD — 규칙 버전 × 카메라 유지율. 기본 최근 7일.
export async function GET(req: NextRequest) {
  const owner = await requireOwner(req);
  if (!owner.ok) return owner.response;
  const now = new Date();
  const to = parseDate(req.nextUrl.searchParams.get('to'), now);
  const from = parseDate(req.nextUrl.searchParams.get('from'), new Date(now.getTime() - 7 * DAY_MS));
  if (!from || !to || from >= to) return NextResponse.json({ detail: 'from/to 날짜가 잘못됐어.', code: 'invalid_request' }, { status: 400 });
  try {
    const { data, error } = await supabaseAdmin.rpc('fn_highlight_rule_stats', { p_from: from.toISOString(), p_to: to.toISOString() });
    if (error) return highlightRpcErrorResponse(error) ?? highlightDatabaseError(error);
    // 유지율 분모는 1차 판정이 있던 확정(decided_count). pending/failed 확정(changed NULL)을 verdict_count 로
    // 나누면 유지율이 깎여 규칙 성능을 오판한다 — pending_initial 은 별도 컬럼으로 그대로 보낸다.
    const rows = ((data ?? []) as StatsRow[]).map((r) => {
      const decided = Number(r.decided_count);
      return {
        ...r,
        verdict_count: Number(r.verdict_count), kept_count: Number(r.kept_count), decided_count: decided,
        o_to_x: Number(r.o_to_x), x_to_o: Number(r.x_to_o), pending_initial: Number(r.pending_initial),
        kept_ratio: decided > 0 ? Number(r.kept_count) / decided : null,
      };
    });
    return NextResponse.json({ from: from.toISOString(), to: to.toISOString(), rows });
  } catch (cause) {
    return highlightDatabaseError(cause);
  }
}
