import { NextRequest, NextResponse } from 'next/server';

import { highlightDatabaseError, highlightRpcErrorResponse } from '@/lib/highlightV4Server';
import { requireLabelingAccess } from '@/lib/labelingAccess';
import { FEATURED_TOP_N } from '@/lib/labelingV4';
import { featuredWindowDays, mapFeaturedRowToItem, parseV4FeaturedRequest } from '@/lib/labelingV4Server';
import { resolveReviewerName } from '../_access';
import { loadFeaturedRows } from '../_featured';
import { attachThumbnails } from '../_thumbnails';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

// GET /api/labeling-v4/featured?days=7&camera_id=… — ⭐ 대표만(하루·카메라당 ≤ top_n). keyset 없음(한 페이지).
// 카메라 필터가 없으면 전체(라벨링 웹은 배정=편의 필터, 권한 아님 — v4 스펙 §4.1).
export async function GET(req: NextRequest) {
  const access = await requireLabelingAccess(req);
  if (!access.ok) return access.response;
  let parsed;
  try {
    parsed = parseV4FeaturedRequest(req.nextUrl.searchParams);
  } catch (e) {
    return NextResponse.json({ detail: `요청 값이 잘못됐어(${(e as Error).message}).`, code: 'invalid_request' }, { status: 400 });
  }
  try {
    const win = featuredWindowDays(new Date(), parsed.days);
    const rows = await loadFeaturedRows({ cameraIds: parsed.cameraIds, from: win.from, to: win.to });
    const items = rows
      .filter((r) => r.tier === 'featured')
      .map((r) => mapFeaturedRowToItem(r, FEATURED_TOP_N, (reviewerId, displayName) => resolveReviewerName({ reviewerId, displayName })));
    await attachThumbnails(items);
    return NextResponse.json({ items, has_more: false, next_cursor: null });
  } catch (cause) {
    return highlightRpcErrorResponse(cause) ?? highlightDatabaseError(cause);
  }
}
