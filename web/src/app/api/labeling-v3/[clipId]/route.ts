import { NextRequest, NextResponse } from 'next/server';

import {
  mapMotionDetailRow,
  motionLabelingDatabaseError,
  type MotionDetailRow,
} from '@/lib/labelingV3Server';
import { loadMotionClipAccess } from '../_access';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

// GET /api/labeling-v3/[clipId] — motion_clip 상세(설계 §5·§9).
//
// owner 는 모든 clip, labeler 는 label 이거나 본인 세션 있는 clip 만(접근 판정은 _access).
// GT 잠금 전에는 prediction/verdict/evidence 를 응답에 담지 않는다(mapMotionDetailRow 가 은닉).
// media_ready 는 r2_key 존재 여부로만 계산하고 raw r2_key 는 통과시키지 않는다.
export async function GET(req: NextRequest, { params }: { params: { clipId: string } }) {
  try {
    const acc = await loadMotionClipAccess(req, params.clipId);
    if (!acc.ok) return acc.response;

    const detailRow: MotionDetailRow = {
      clip_id: acc.clip.id,
      camera_id: acc.clip.camera_id,
      camera_name: acc.clip.camera_name,
      started_at: acc.clip.started_at,
      duration_sec: acc.clip.duration_sec,
      media_ready: acc.clip.r2_key != null,
      state: acc.ownerDecision ?? 'unreviewed',
      state_updated_at: acc.stateUpdatedAt,
      session: acc.session,
    };
    return NextResponse.json(mapMotionDetailRow(detailRow));
  } catch (cause) {
    return motionLabelingDatabaseError(cause);
  }
}
