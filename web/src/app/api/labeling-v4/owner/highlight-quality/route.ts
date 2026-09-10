import { NextRequest, NextResponse } from 'next/server';
import { mapHighlightQuality } from '@/lib/highlightQuality';
import { highlightDatabaseError, highlightRpcErrorResponse } from '@/lib/highlightV4Server';
import { requireOwner } from '@/lib/labelingAccess';
import { supabaseAdmin } from '@/lib/supabase';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
const DAY_MS = 86400000;
function date(value: string | null, fallback: Date): Date | null {
  if (value === null) return fallback;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const parsed = new Date(`${value}T00:00:00.000Z`);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value ? parsed : null;
}

export async function GET(req: NextRequest) {
  const owner = await requireOwner(req);
  if (!owner.ok) return owner.response;
  const to = date(req.nextUrl.searchParams.get('to'), new Date());
  const from = date(req.nextUrl.searchParams.get('from'), new Date((to?.getTime() ?? Date.now()) - 7 * DAY_MS));
  if (!from || !to || from >= to || to.getTime() - from.getTime() > 31 * DAY_MS) {
    return NextResponse.json({detail:'from/to는 올바른 날짜로 31일 이내여야 해.',code:'invalid_request'}, {status:400});
  }
  try {
    const {data,error} = await supabaseAdmin.rpc('fn_highlight_quality_stats', {p_from:from.toISOString(),p_to:to.toISOString()});
    if (error) return highlightRpcErrorResponse(error) ?? highlightDatabaseError(error);
    return NextResponse.json({from:from.toISOString(),to:to.toISOString(),...mapHighlightQuality(data)});
  } catch (cause) { return highlightDatabaseError(cause); }
}
