import { NextRequest, NextResponse } from 'next/server';

import {
  mapGmeObservedMovingTimeRow,
  mapMotionDetailRow,
  motionLabelingDatabaseError,
  readGmeActiveDetectorIdentity,
  type GmeObservedMovingTimeRow,
  type MotionDetailRow,
} from '@/lib/labelingV3Server';
import { supabaseAdmin } from '@/lib/supabase';
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
    const detail = mapMotionDetailRow(detailRow);

    // GME 지표도 prediction과 같은 blind 경계를 따른다. 최초 GT 잠금 전에는 env를 읽거나
    // RPC를 호출하지 않아 모델 결과가 사람의 독립 판정을 유도할 가능성 자체를 없앤다.
    if (
      detail.session?.stage === 'gt_locked' ||
      detail.session?.stage === 'completed'
    ) {
      const detectorIdentity = readGmeActiveDetectorIdentity();
      const { data, error } = await supabaseAdmin.rpc(
        'fn_get_gme_observed_moving_time_v1',
        {
          p_clip_id: params.clipId,
          p_detector_identity: detectorIdentity,
        },
      );
      if (error) throw error;
      if (!Array.isArray(data) || data.length !== 1) {
        throw new Error('invalid_gme_observed_moving_time_result_count');
      }
      detail.gme_activity = mapGmeObservedMovingTimeRow(
        data[0] as GmeObservedMovingTimeRow,
      );
    }

    return NextResponse.json(detail);
  } catch (cause) {
    return motionLabelingDatabaseError(cause);
  }
}
