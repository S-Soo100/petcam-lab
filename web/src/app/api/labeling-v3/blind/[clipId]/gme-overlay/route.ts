import { NextRequest, NextResponse } from 'next/server';

import { fetchAndParseGmeOverlay, loadCurrentGmeOverlaySource } from '@/lib/gmeOverlayServer';
import { readGmeActiveContract } from '@/lib/labelingV3Server';
import { presignGet } from '@/lib/r2';
import { loadBlindSlotAccess } from '../../_access';

export const runtime = 'nodejs';
const GME_ARTIFACT_URL_TTL_SEC = 300;

function unavailable(durationSec: number): NextResponse {
  return NextResponse.json({
    available: false,
    overlay_revision: null,
    duration_sec: durationSec,
    points: [],
  });
}

// GME artifact의 R2 key/run UUID/detector identity는 서버 안에서만 사용한다.
// overlay 장애는 사람 라벨링 자체를 막지 않도록 안전한 unavailable 응답으로 접는다.
export async function GET(req: NextRequest, { params }: { params: { clipId: string } }) {
  const cohortId = req.nextUrl.searchParams.get('cohort_id');
  const access = await loadBlindSlotAccess(req, params.clipId, cohortId);
  if (!access.ok) return access.response;

  try {
    const contract = readGmeActiveContract();
    const source = await loadCurrentGmeOverlaySource(
      params.clipId,
      contract.detector_identity,
      contract.algorithm_version,
    );
    if (!source) return unavailable(access.clip.duration_sec);
    const signedUrl = await presignGet(source.artifactKey, GME_ARTIFACT_URL_TTL_SEC, {
      // R2 metadata의 Content-Encoding:gzip을 fetch가 자동 해제하지 않게 해
      // DB에 고정된 compressed byte count와 SHA를 원본 바이트로 검증한다.
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
      available: true,
      overlay_revision: source.overlayRevision,
      duration_sec: parsed.duration_sec,
      points: parsed.points,
    });
  } catch (cause) {
    console.error('[blind-review] GME overlay unavailable', cause);
    return unavailable(access.clip.duration_sec);
  }
}
