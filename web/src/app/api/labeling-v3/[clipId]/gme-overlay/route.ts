import { NextRequest, NextResponse } from 'next/server';

import { fetchAndParseGmeOverlay, loadCurrentGmeOverlayStatus } from '@/lib/gmeOverlayServer';
import { presignGet } from '@/lib/r2';
import { loadMotionClipAccess } from '../../_access';

export const runtime = 'nodejs';
const GME_ARTIFACT_URL_TTL_SEC = 300;

function empty(state: 'pending' | 'unavailable', durationSec: number): NextResponse {
  return NextResponse.json({
    state,
    available: false,
    model_version: 'v2.6',
    overlay_revision: null,
    duration_sec: durationSec,
    points: [],
  });
}

// Owner 직접 라벨링에서도 익명화된 좌표만 보낸다. run/key/identity는 서버 밖으로 내보내지 않는다.
export async function GET(req: NextRequest, { params }: { params: { clipId: string } }) {
  const access = await loadMotionClipAccess(req, params.clipId);
  if (!access.ok) return access.response;

  try {
    const status = await loadCurrentGmeOverlayStatus(params.clipId);
    if (status.state !== 'ready') return empty(status.state, access.clip.duration_sec);
    const { source } = status;
    const signedUrl = await presignGet(source.artifactKey, GME_ARTIFACT_URL_TTL_SEC, {
      responseContentEncoding: 'identity',
    });
    const parsed = await fetchAndParseGmeOverlay(
      signedUrl,
      source.overlayRevision,
      source.artifactBytes,
    );
    if (Math.abs(parsed.duration_sec - access.clip.duration_sec) > 1) {
      throw new Error('GME artifact duration mismatch');
    }
    return NextResponse.json({
      state: 'ready',
      available: true,
      model_version: 'v2.6',
      overlay_revision: source.overlayRevision,
      duration_sec: parsed.duration_sec,
      points: parsed.points,
    });
  } catch (cause) {
    console.error('[owner-labeling] GME overlay unavailable', cause);
    return empty('unavailable', access.clip.duration_sec);
  }
}
