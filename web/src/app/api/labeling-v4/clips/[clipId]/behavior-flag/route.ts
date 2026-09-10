import { NextRequest, NextResponse } from 'next/server';

import { highlightDatabaseError, highlightRpcErrorResponse } from '@/lib/highlightV4Server';
import { loadV4ClipAccess } from '../../../_access';
import { setBehaviorFlag } from '../../../_behavior-flag';
import { HighlightRpcError } from '../../../_highlight';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

// POST /api/labeling-v4/clips/[clipId]/behavior-flag  { flagged: boolean }
// 하이라이트 O/X 와 별개의 "의미있는 행동" 체크. 승인 사용자면 누구나 체크, 해제는 체크한 사람·owner(403).
export async function POST(req: NextRequest, { params }: { params: { clipId: string } }) {
  try {
    const access = await loadV4ClipAccess(req, params.clipId);
    if (!access.ok) return access.response;
    let body: { flagged?: unknown };
    try { body = await req.json(); } catch { return NextResponse.json({ detail: 'JSON 본문이 필요해.', code: 'invalid_request' }, { status: 400 }); }
    if (typeof body.flagged !== 'boolean') return NextResponse.json({ detail: 'flagged 는 true/false 여야 해.', code: 'invalid_request' }, { status: 400 });
    const flag = await setBehaviorFlag(access.clip.id, access.userId, access.isOwner, body.flagged);
    return NextResponse.json(flag);
  } catch (cause) {
    if (cause instanceof HighlightRpcError) return highlightRpcErrorResponse(cause.cause) ?? highlightDatabaseError(cause.cause);
    return highlightDatabaseError(cause);
  }
}
