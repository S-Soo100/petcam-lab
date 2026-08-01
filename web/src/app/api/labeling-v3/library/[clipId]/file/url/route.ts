import { NextRequest, NextResponse } from 'next/server';

import { supabaseAdmin } from '@/lib/supabase';
import { databaseUnavailable } from '@/lib/apiErrors';
import { presignGet, SIGNED_URL_TTL_SEC } from '@/lib/r2';
import { requireProductionLabelingAccess } from '@/lib/labelingAccess';
import { isValidUuid } from '@/lib/motionBlindReviewServer';
import { isMotionMediaDeleted } from '@/lib/labelingV3Server';

export const runtime = 'nodejs';

// GET /api/labeling-v3/library/[clipId]/file/url — 공용 읽기 전용 재생 서명(설계 §5.3·§10).
//
// 승인 사용자(owner·라벨러)면 누구나 모든 카메라의 재생 가능 영상을 볼 수 있다(영상 보관함).
// 인증 먼저 → UUID 검증 → r2_key 만 select → 짧게 서명. raw key 는 응답에 담지 않는다.
// r2_key 없음=410, 서명 실패=502.
export async function GET(req: NextRequest, { params }: { params: { clipId: string } }) {
  const access = await requireProductionLabelingAccess(req);
  if (!access.ok) return access.response;

  if (!isValidUuid(params.clipId)) {
    return NextResponse.json({ detail: '잘못된 clip id', code: 'invalid_request' }, { status: 400 });
  }

  try {
    // 짧은 영상 자동 제외로 원본이 삭제된 clip 은 서명 전에 410(설계 §6.2). signer 호출 0.
    if (await isMotionMediaDeleted(params.clipId)) {
      return NextResponse.json(
        { detail: '원본이 삭제된 영상이야.', code: 'media_deleted' },
        { status: 410 },
      );
    }

    const { data, error } = await supabaseAdmin
      .from('motion_clips')
      .select('r2_key')
      .eq('id', params.clipId)
      .limit(1);
    if (error) return databaseUnavailable('labeling library media', error);
    const clip = (data ?? [])[0] as { r2_key: string | null } | undefined;
    if (!clip || clip.r2_key == null) {
      return NextResponse.json(
        { detail: '원본 영상이 없어 재생할 수 없어.', code: 'media_unavailable' },
        { status: 410 },
      );
    }

    let url: string;
    try {
      const download = req.nextUrl.searchParams.get('download') === '1';
      url = download
        ? await presignGet(clip.r2_key, SIGNED_URL_TTL_SEC, {
            downloadFilename: `petcam-${params.clipId}.mp4`,
          })
        : await presignGet(clip.r2_key, SIGNED_URL_TTL_SEC);
    } catch (signErr) {
      console.error('[labeling library] signed url failure', signErr);
      return NextResponse.json(
        { detail: '영상 URL 발급에 실패했어. 잠시 후 다시 시도해.', code: 'signing_failed' },
        { status: 502 },
      );
    }

    const download = req.nextUrl.searchParams.get('download') === '1';
    return NextResponse.json(download
      ? { url, filename: `petcam-${params.clipId}.mp4`, expires_in: SIGNED_URL_TTL_SEC }
      : { url, expires_in: SIGNED_URL_TTL_SEC });
  } catch (cause) {
    return databaseUnavailable('labeling library media', cause);
  }
}
