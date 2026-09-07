import { NextRequest, NextResponse } from 'next/server';

import { highlightDatabaseError, highlightRpcErrorResponse } from '@/lib/highlightV4Server';
import { loadV4ClipAccess } from '../../../_access';
import { HighlightRpcError, loadHighlightDetail } from '../../../_highlight';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

// GET /api/labeling-v4/clips/[clipId]/highlight — 현재값(사람 확정 우선) + 1차 판정 상세.
// 1차 판정은 저장된 값이 아니라 DB 함수가 지금 계산한 값이다(스펙 §4.2). 계산은 _highlight.ts 와 공유.
export async function GET(req: NextRequest, { params }: { params: { clipId: string } }) {
  try {
    const access = await loadV4ClipAccess(req, params.clipId);
    if (!access.ok) return access.response;
    return NextResponse.json(await loadHighlightDetail(params.clipId));
  } catch (cause) {
    if (cause instanceof HighlightRpcError) return highlightRpcErrorResponse(cause.cause) ?? highlightDatabaseError(cause.cause);
    return highlightDatabaseError(cause);
  }
}
