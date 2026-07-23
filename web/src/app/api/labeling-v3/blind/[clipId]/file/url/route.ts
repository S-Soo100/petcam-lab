import { NextRequest, NextResponse } from 'next/server';

import { presignGet, SIGNED_URL_TTL_SEC } from '@/lib/r2';
import { blindDatabaseError } from '@/lib/motionBlindReviewServer';
import { loadBlindSlotAccess } from '../../../_access';

export const runtime = 'nodejs';

// GET /api/labeling-v3/blind/[clipId]/file/url?cohort_id=<canary uuid>
//
// 본인 slot 인가 후에만 r2_key 를 다시 읽어 짧게 서명한다(설계 §9). 응답에는 { url, expires_in }
// 만 담고 raw key 는 비노출. r2_key 없음=410, 서명 실패=502.
export async function GET(req: NextRequest, { params }: { params: { clipId: string } }) {
  try {
    const cohortId = req.nextUrl.searchParams.get('cohort_id');
    const acc = await loadBlindSlotAccess(req, params.clipId, cohortId);
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
      console.error('[blind-review] signed url failure', signErr);
      return NextResponse.json(
        { detail: '영상 URL 발급에 실패했어. 잠시 후 다시 시도해.', code: 'signing_failed' },
        { status: 502 },
      );
    }

    return NextResponse.json({ url, expires_in: SIGNED_URL_TTL_SEC });
  } catch (cause) {
    return blindDatabaseError(cause);
  }
}
