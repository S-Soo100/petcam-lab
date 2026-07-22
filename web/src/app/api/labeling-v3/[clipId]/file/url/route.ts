import { NextRequest, NextResponse } from 'next/server';

import { presignGet, SIGNED_URL_TTL_SEC } from '@/lib/r2';
import { motionLabelingDatabaseError } from '@/lib/labelingV3Server';
import { loadMotionClipAccess } from '../../../_access';

export const runtime = 'nodejs';

// GET /api/labeling-v3/[clipId]/file/url — motion_clip R2 signed URL(설계 §9·§12).
//
// r2_key 는 서버가 다시 읽어 짧게 서명하고 응답에는 { url, expires_in } 만 담는다(raw key 비노출).
// owner 는 clip 소유 무관, labeler 는 label/본인 세션 clip 만(접근 판정은 _access).
// r2_key 없음=410, 서명 실패=502. <video src> 는 cross-origin 에 Authorization 을 못 넣으므로
// 단발 signed URL 만 넘긴다(R2 가 직접 서빙, Range/seek 도 R2).
export async function GET(req: NextRequest, { params }: { params: { clipId: string } }) {
  try {
    const acc = await loadMotionClipAccess(req, params.clipId);
    if (!acc.ok) return acc.response;

    if (acc.clip.r2_key == null) {
      return NextResponse.json(
        { detail: '원본 영상이 없어 재생할 수 없어.', code: 'media_unavailable' },
        { status: 410 },
      );
    }

    let url: string;
    try {
      url = await presignGet(acc.clip.r2_key, SIGNED_URL_TTL_SEC);
    } catch (signErr) {
      // 서명 실패 원문(자격증명 등)은 로그에만, 응답은 일반화된 502.
      console.error('[labeling-v3] signed url failure', signErr);
      return NextResponse.json(
        { detail: '영상 URL 발급에 실패했어. 잠시 후 다시 시도해.', code: 'signing_failed' },
        { status: 502 },
      );
    }

    return NextResponse.json({ url, expires_in: SIGNED_URL_TTL_SEC });
  } catch (cause) {
    return motionLabelingDatabaseError(cause);
  }
}
