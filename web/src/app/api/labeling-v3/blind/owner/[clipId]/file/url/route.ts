import { NextRequest, NextResponse } from 'next/server';

import { requireOwner } from '@/lib/labelingAccess';
import { isMotionMediaDeleted } from '@/lib/labelingV3Server';
import {
  blindBadRequest,
  blindDatabaseError,
  isValidUuid,
} from '@/lib/motionBlindReviewServer';
import { presignGet, SIGNED_URL_TTL_SEC } from '@/lib/r2';
import { supabaseAdmin } from '@/lib/supabase';
import { loadOwnerConflictScope } from '../../../../_access';

export const runtime = 'nodejs';

// Owner 불일치 검수 전용 signed URL. 라벨러 slot 인가 경로를 우회하지 않고 별도 owner gate에서
// 정확한 clip×cohort consensus를 먼저 확인한다. raw r2_key는 응답에 절대 담지 않는다.
export async function GET(
  req: NextRequest,
  { params }: { params: { clipId: string } },
) {
  const owner = await requireOwner(req);
  if (!owner.ok) return owner.response;
  if (!isValidUuid(params.clipId)) return blindBadRequest('잘못된 clip id');

  try {
    const scoped = await loadOwnerConflictScope(
      req.nextUrl.searchParams.get('cohort_id'),
    );
    if (!scoped.ok) return scoped.response;

    let consensusQuery = supabaseAdmin
      .from('motion_clip_consensus')
      .select('status')
      .eq('clip_id', params.clipId)
      .eq('cohort_kind', scoped.scope.cohortKind);
    consensusQuery = scoped.scope.cohortId
      ? consensusQuery.eq('cohort_id', scoped.scope.cohortId)
      : consensusQuery.is('cohort_id', null);
    const { data: consensusData, error: consensusError } =
      await consensusQuery.limit(1);
    if (consensusError) throw consensusError;
    const consensus = (consensusData ?? [])[0] as
      | { status?: string }
      | undefined;
    if (
      !consensus ||
      (consensus.status !== 'conflict' &&
        consensus.status !== 'owner_resolved')
    ) {
      return NextResponse.json(
        { detail: '대상을 찾을 수 없어.', code: 'not_found' },
        { status: 404 },
      );
    }

    // consensus scope 확인 뒤에만 media key를 읽어 cross-cohort clip probing을 막는다.
    const { data: clipData, error: clipError } = await supabaseAdmin
      .from('motion_clips')
      .select('r2_key')
      .eq('id', params.clipId)
      .limit(1);
    if (clipError) throw clipError;
    const clip = (clipData ?? [])[0] as
      | { r2_key: string | null }
      | undefined;
    if (!clip || clip.r2_key == null) {
      return NextResponse.json(
        {
          detail: '원본 영상이 없어 재생할 수 없어.',
          code: 'media_unavailable',
        },
        { status: 410 },
      );
    }

    if (await isMotionMediaDeleted(params.clipId)) {
      return NextResponse.json(
        { detail: '원본이 삭제된 영상이야.', code: 'media_deleted' },
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
    } catch (signError) {
      // signer 오류에는 credential/key 문맥이 섞일 수 있어 원문 대신 오류 종류만 기록한다.
      console.error(
        '[blind-owner-review] signed url failure',
        signError instanceof Error ? signError.name : 'unknown_error',
      );
      return NextResponse.json(
        {
          detail: '영상 URL 발급에 실패했어. 잠시 후 다시 시도해.',
          code: 'signing_failed',
        },
        { status: 502 },
      );
    }
    const download = req.nextUrl.searchParams.get('download') === '1';
    return NextResponse.json(download
      ? { url, filename: `petcam-${params.clipId}.mp4`, expires_in: SIGNED_URL_TTL_SEC }
      : { url, expires_in: SIGNED_URL_TTL_SEC });
  } catch (cause) {
    return blindDatabaseError(cause);
  }
}
