import { NextRequest, NextResponse } from 'next/server';

import { loadClipWithPerms } from '@/lib/clipPerms';
import { clipDownloadFilename } from '@/lib/labelingV2';
import { presignGet, SIGNED_URL_TTL_SEC } from '@/lib/r2';

export const runtime = 'nodejs';

export async function GET(
  req: NextRequest,
  { params }: { params: { id: string } },
) {
  const result = await loadClipWithPerms(req, params.id);
  if (!result.ok) return result.response;

  const { clip } = result.access;
  if (!clip.r2_key) {
    return NextResponse.json(
      { detail: 'clip has no R2 object (local-only or pre-R2 era)' },
      { status: 410 },
    );
  }

  const filename = clipDownloadFilename(String(clip.started_at), params.id);
  const url = await presignGet(clip.r2_key, SIGNED_URL_TTL_SEC, {
    downloadFilename: filename,
  });
  return NextResponse.json({
    url,
    filename,
    ttl_sec: SIGNED_URL_TTL_SEC,
    type: 'r2',
  });
}
