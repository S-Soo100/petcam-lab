import { NextRequest, NextResponse } from 'next/server';

import { blindDatabaseError, mapBlindClipDetailRow } from '@/lib/motionBlindReviewServer';
import { loadBlindSlotAccess } from '../_access';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

// GET /api/labeling-v3/blind/[clipId]?cohort_id=<canary uuid>
//
// 본인 slot 이 있을 때만 상세를 준다(설계 §7). 상대 제출·r2_key·consensus 상태는 담지 않는다.
// read-only — lease 를 만들거나 상태를 바꾸지 않는다. cohort_id 없으면 live scope.
export async function GET(req: NextRequest, { params }: { params: { clipId: string } }) {
  try {
    const cohortId = req.nextUrl.searchParams.get('cohort_id');
    const acc = await loadBlindSlotAccess(req, params.clipId, cohortId);
    if (!acc.ok) return acc.response;
    return NextResponse.json({ clip: mapBlindClipDetailRow(acc.detailRow) });
  } catch (cause) {
    return blindDatabaseError(cause);
  }
}
