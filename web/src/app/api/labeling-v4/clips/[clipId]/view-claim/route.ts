import { NextRequest, NextResponse } from 'next/server';

import { loadV4ClipAccess } from '../../../_access';
import { claimView } from '../../../_claims';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

// POST /api/labeling-v4/clips/[clipId]/view-claim — "이 영상 보는 중" 힌트(UX ⑤). 응답은 항상 { ok: true }.
export async function POST(req: NextRequest, { params }: { params: { clipId: string } }) {
  const access = await loadV4ClipAccess(req, params.clipId);
  if (!access.ok) return access.response;
  await claimView(access.clip.id, access.userId);
  return NextResponse.json({ ok: true });
}
