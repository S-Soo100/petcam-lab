// v3 owner overlay 와 동일, access 만 v4(loadV4ClipAccess).
import { NextRequest, NextResponse } from 'next/server';

import { fetchAndParseGmeOverlay, loadCurrentGmeOverlaySource } from '@/lib/gmeOverlayServer';
import { readGmeActiveContract } from '@/lib/labelingV3Server';
import { presignGet } from '@/lib/r2';
import { loadV4ClipAccess } from '../../../_access';

export const runtime = 'nodejs';
const GME_ARTIFACT_URL_TTL_SEC = 300;

function unavailable(durationSec: number | null) {
  return NextResponse.json({ available: false, overlay_revision: null, duration_sec: durationSec ?? 0, points: [], intervals: [] });
}

export async function GET(req: NextRequest, { params }: { params: { clipId: string } }) {
  const access = await loadV4ClipAccess(req, params.clipId);
  if (!access.ok) return access.response;
  try {
    const contract = readGmeActiveContract();
    const source = await loadCurrentGmeOverlaySource(params.clipId, contract.detector_identity, contract.algorithm_version);
    if (!source) return unavailable(access.clip.duration_sec);
    const signedUrl = await presignGet(source.artifactKey, GME_ARTIFACT_URL_TTL_SEC, { responseContentEncoding: 'identity' });
    const parsed = await fetchAndParseGmeOverlay(signedUrl, source.overlayRevision, source.artifactBytes);
    if (access.clip.duration_sec !== null && Math.abs(parsed.duration_sec - access.clip.duration_sec) > 1) throw new Error('GME artifact duration mismatch');
    return NextResponse.json({ available: true, overlay_revision: source.overlayRevision, duration_sec: parsed.duration_sec, points: parsed.points, intervals: parsed.intervals });
  } catch (cause) {
    console.error('[labeling-v4] GME overlay unavailable', cause);
    return unavailable(access.clip.duration_sec);
  }
}
