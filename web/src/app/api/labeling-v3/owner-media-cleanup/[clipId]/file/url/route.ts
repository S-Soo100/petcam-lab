import { NextRequest, NextResponse } from 'next/server';

import { requireOwner } from '@/lib/labelingAccess';
import { motionLabelingDatabaseError, motionRpcErrorResponse } from '@/lib/labelingV3Server';
import { presignGet, SIGNED_URL_TTL_SEC } from '@/lib/r2';
import { supabaseAdmin } from '@/lib/supabase';

export const runtime = 'nodejs';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export async function GET(req: NextRequest, { params }: { params: { clipId: string } }) {
  const owner = await requireOwner(req);
  if (!owner.ok) return owner.response;
  if (!UUID.test(params.clipId)) {
    return NextResponse.json({ detail: '잘못된 clip id', code: 'invalid_request' }, { status: 400 });
  }
  try {
    const { data, error } = await supabaseAdmin.rpc('fn_get_rba_owner_media_cleanup_key_v1', {
      p_owner_id: owner.userId,
      p_clip_id: params.clipId,
    });
    if (error) return motionRpcErrorResponse(error) ?? motionLabelingDatabaseError(error);
    const r2Key = ((data ?? []) as { r2_key?: string }[])[0]?.r2_key;
    if (!r2Key) {
      return NextResponse.json({ detail: '재생 가능한 정리 영상이 아니야.', code: 'not_found' }, { status: 404 });
    }
    const download = req.nextUrl.searchParams.get('download') === '1';
    const filename = `petcam-cleanup-${params.clipId}.mp4`;
    const url = await presignGet(
      r2Key,
      SIGNED_URL_TTL_SEC,
      download ? { downloadFilename: filename } : undefined,
    );
    return NextResponse.json(
      download
        ? { url, filename, expires_in: SIGNED_URL_TTL_SEC }
        : { url, expires_in: SIGNED_URL_TTL_SEC },
    );
  } catch (cause) {
    return motionLabelingDatabaseError(cause);
  }
}
