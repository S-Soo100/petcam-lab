// v3 owner route 와 동일 본문, access 만 v4(loadV4ClipAccess).
import { NextRequest, NextResponse } from 'next/server';

import { presignGet, SIGNED_URL_TTL_SEC } from '@/lib/r2';
import { isMotionMediaDeleted, motionLabelingDatabaseError } from '@/lib/labelingV3Server';
import { loadV4ClipAccess } from '../../../../_access';

export const runtime = 'nodejs';

export async function GET(req: NextRequest, { params }: { params: { clipId: string } }) {
  try {
    const acc = await loadV4ClipAccess(req, params.clipId);
    if (!acc.ok) return acc.response;
    if (acc.clip.r2_key == null) return NextResponse.json({ detail: '원본 영상이 없어 재생할 수 없어.', code: 'media_unavailable' }, { status: 410 });
    if (await isMotionMediaDeleted(params.clipId)) return NextResponse.json({ detail: '원본이 삭제된 영상이야.', code: 'media_deleted' }, { status: 410 });
    const download = req.nextUrl.searchParams.get('download') === '1';
    let url: string;
    try {
      url = download
        ? await presignGet(acc.clip.r2_key, SIGNED_URL_TTL_SEC, { downloadFilename: `petcam-${params.clipId}.mp4` })
        : await presignGet(acc.clip.r2_key, SIGNED_URL_TTL_SEC);
    } catch (signErr) {
      console.error('[labeling-v4] signed url failure', signErr);
      return NextResponse.json({ detail: '영상 URL 발급에 실패했어. 잠시 후 다시 시도해.', code: 'signing_failed' }, { status: 502 });
    }
    return NextResponse.json(download ? { url, filename: `petcam-${params.clipId}.mp4`, expires_in: SIGNED_URL_TTL_SEC } : { url, expires_in: SIGNED_URL_TTL_SEC });
  } catch (cause) {
    return motionLabelingDatabaseError(cause);
  }
}
