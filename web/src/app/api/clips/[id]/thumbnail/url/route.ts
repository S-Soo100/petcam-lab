import { NextRequest, NextResponse } from 'next/server';

import { loadClipWithPerms } from '@/lib/clipPerms';
import { thumbnailKeyForClip } from '@/lib/labelingV2';
import { presignGet, SIGNED_URL_TTL_SEC } from '@/lib/r2';

export const runtime = 'nodejs';

export async function GET(
  req: NextRequest,
  { params }: { params: { id: string } },
) {
  const result = await loadClipWithPerms(req, params.id);
  if (!result.ok) return result.response;

  let key: string;
  try {
    key = thumbnailKeyForClip(result.access.clip);
  } catch (error) {
    return NextResponse.json(
      { detail: (error as Error).message },
      { status: 410 },
    );
  }

  const url = await presignGet(key, SIGNED_URL_TTL_SEC);
  return NextResponse.json({ url, ttl_sec: SIGNED_URL_TTL_SEC, type: 'r2' });
}
