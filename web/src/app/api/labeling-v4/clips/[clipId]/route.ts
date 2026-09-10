import { NextRequest, NextResponse } from 'next/server';

import { highlightDatabaseError, highlightRpcErrorResponse } from '@/lib/highlightV4Server';
import { isMotionMediaDeleted } from '@/lib/labelingV3Server';
import { loadV4ClipAccess } from '../../_access';
import { loadBehaviorFlag } from '../../_behavior-flag';
import { loadFeaturedForClip } from '../../_featured';
import { HighlightRpcError, loadHighlightDetail } from '../../_highlight';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

// GET /api/labeling-v4/clips/[clipId] — clip 메타 + highlight 상세. r2_key 는 응답에 싣지 않는다.
export async function GET(req: NextRequest, { params }: { params: { clipId: string } }) {
  try {
    const access = await loadV4ClipAccess(req, params.clipId);
    if (!access.ok) return access.response;
    const { clip } = access;
    const mediaReady = clip.r2_key !== null && !(await isMotionMediaDeleted(clip.id));
    const highlight = await loadHighlightDetail(clip.id);
    const behaviorFlag = await loadBehaviorFlag(clip.id);
    // ⭐ 대표 tier — 현재 O 일 때만 그 클립의 하루 창으로 한 번 계산(보조 정보, 실패 시 null).
    const featured = await loadFeaturedForClip({ id: clip.id, camera_id: clip.camera_id, started_at: clip.started_at }, highlight.current.value === true);
    return NextResponse.json({ id: clip.id, camera_id: clip.camera_id, started_at: clip.started_at, duration_sec: clip.duration_sec, media_ready: mediaReady, highlight, behavior_flag: behaviorFlag, featured });
  } catch (cause) {
    if (cause instanceof HighlightRpcError) return highlightRpcErrorResponse(cause.cause) ?? highlightDatabaseError(cause.cause);
    return highlightDatabaseError(cause);
  }
}
