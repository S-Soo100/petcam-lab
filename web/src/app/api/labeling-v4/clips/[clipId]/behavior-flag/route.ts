import { NextRequest, NextResponse } from 'next/server';

import { highlightDatabaseError, highlightRpcErrorResponse } from '@/lib/highlightV4Server';
import { isBehaviorKind } from '@/lib/labelingV4';
import { loadV4ClipAccess } from '../../../_access';
import { setBehaviorMark } from '../../../_behavior-flag';
import { HighlightRpcError } from '../../../_highlight';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

// POST /api/labeling-v4/clips/[clipId]/behavior-flag  { kind?: 'meaningful'|'wheel'|'fall'|'closeup', flagged: boolean }
// 하이라이트 O/X 와 별개의 행동 표시 4종(2026-09-11). kind 생략 = meaningful(구버전 호환). 응답은 4종 전체 상태.
// 승인 사용자면 누구나 표시, 해제는 표시한 사람·owner(403).
export async function POST(req: NextRequest, { params }: { params: { clipId: string } }) {
  try {
    const access = await loadV4ClipAccess(req, params.clipId);
    if (!access.ok) return access.response;
    let body: { flagged?: unknown; kind?: unknown };
    try { body = await req.json(); } catch { return NextResponse.json({ detail: 'JSON 본문이 필요해.', code: 'invalid_request' }, { status: 400 }); }
    if (typeof body.flagged !== 'boolean') return NextResponse.json({ detail: 'flagged 는 true/false 여야 해.', code: 'invalid_request' }, { status: 400 });
    const kind = body.kind === undefined ? 'meaningful' : body.kind;
    if (!isBehaviorKind(kind)) return NextResponse.json({ detail: 'kind 는 meaningful·wheel·fall·closeup 중 하나여야 해.', code: 'invalid_request' }, { status: 400 });
    const marks = await setBehaviorMark(access.clip.id, access.userId, access.isOwner, kind, body.flagged);
    return NextResponse.json(marks);
  } catch (cause) {
    if (cause instanceof HighlightRpcError) return highlightRpcErrorResponse(cause.cause) ?? highlightDatabaseError(cause.cause);
    return highlightDatabaseError(cause);
  }
}
