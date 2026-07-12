import { NextRequest, NextResponse } from 'next/server';

import { loadClipWithPerms } from '@/lib/clipPerms';
import { revealPrediction } from '@/lib/labelingV2';
import { databaseError, loadOwnSession } from '../_helpers';

export const runtime = 'nodejs';

export async function GET(
  req: NextRequest,
  { params }: { params: { clipId: string } },
) {
  const accessResult = await loadClipWithPerms(req, params.clipId);
  if (!accessResult.ok) return accessResult.response;

  try {
    const session = await loadOwnSession(
      params.clipId,
      accessResult.access.userId,
    );
    const safeSession = session
      ? { ...session, prediction_snapshot: revealPrediction(session, session.prediction_snapshot) }
      : null;
    const clip = accessResult.access.clip;
    return NextResponse.json({
      clip,
      session: safeSession,
      system_metadata: {
        started_at: clip.started_at ?? null,
        ended_at: clip.ended_at ?? null,
        duration_sec: clip.duration_sec ?? null,
        camera_id: clip.camera_id ?? null,
        has_motion: clip.has_motion ?? null,
        motion_score: clip.motion_score ?? null,
      },
    });
  } catch (error) {
    return databaseError(error);
  }
}
