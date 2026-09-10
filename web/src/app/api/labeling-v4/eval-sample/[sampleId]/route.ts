import { NextRequest, NextResponse } from 'next/server';

import { highlightDatabaseError } from '@/lib/highlightV4Server';
import { requireLabelingAccess } from '@/lib/labelingAccess';
import { isEvalSampleId } from '@/lib/labelingV4';
import { supabaseAdmin } from '@/lib/supabase';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

// GET /api/labeling-v4/eval-sample/[sampleId] — 봉인 평가 표본 진행(전체/사람 확정). 승인 사용자 누구나(읽기).
export async function GET(req: NextRequest, { params }: { params: { sampleId: string } }) {
  const access = await requireLabelingAccess(req);
  if (!access.ok) return access.response;
  if (!isEvalSampleId(params.sampleId)) return NextResponse.json({ detail: '표본 id 가 잘못됐어.', code: 'invalid_request' }, { status: 400 });
  try {
    const { data, error } = await supabaseAdmin.rpc('fn_eval_sample_progress', { p_sample_id: params.sampleId });
    if (error) throw error;
    const row = (Array.isArray(data) ? data[0] : data) as { total?: unknown; labeled?: unknown } | undefined;
    return NextResponse.json({ sample_id: params.sampleId, total: Number(row?.total ?? 0), labeled: Number(row?.labeled ?? 0) });
  } catch (cause) {
    return highlightDatabaseError(cause);
  }
}
