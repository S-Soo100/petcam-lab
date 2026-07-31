import { NextRequest, NextResponse } from 'next/server';

import { databaseUnavailable } from '@/lib/apiErrors';
import { requireLabelingAccess } from '@/lib/labelingAccess';
import { presignGet, SIGNED_URL_TTL_SEC } from '@/lib/r2';
import { boundaryRpcErrorResponse, isBoundaryUuid } from '@/lib/rbaBoundaryServer';
import { supabaseAdmin } from '@/lib/supabase';

export const runtime = 'nodejs';

export async function GET(
  req: NextRequest,
  { params }: { params: { pairId: string } },
) {
  const access = await requireLabelingAccess(req);
  if (!access.ok) return access.response;
  const side = req.nextUrl.searchParams.get('side');
  if (!isBoundaryUuid(params.pairId) || (side !== 'left' && side !== 'right')) {
    return NextResponse.json({ detail: '영상 요청이 올바르지 않아.' }, { status: 400 });
  }
  try {
    const { data, error } = await supabaseAdmin.rpc('fn_get_rba_boundary_pair_media', {
      p_reviewer_id: access.userId,
      p_pair_id: params.pairId,
      p_side: side,
    });
    if (error) {
      return boundaryRpcErrorResponse(error) ?? databaseUnavailable('rba boundary media', error);
    }
    const rows = (data ?? []) as { r2_key?: unknown }[];
    const key = rows[0]?.r2_key;
    if (typeof key !== 'string' || !key) {
      return NextResponse.json(
        { detail: '원본 영상을 재생할 수 없어.', code: 'media_unavailable' },
        { status: 410 },
      );
    }
    try {
      const url = await presignGet(key, SIGNED_URL_TTL_SEC);
      return NextResponse.json({ url, expires_in: SIGNED_URL_TTL_SEC });
    } catch (cause) {
      console.error('[rba boundary media] signing failed', cause);
      return NextResponse.json({ detail: '영상 URL 발급에 실패했어.' }, { status: 502 });
    }
  } catch (cause) {
    return databaseUnavailable('rba boundary media', cause);
  }
}
