import { NextRequest, NextResponse } from 'next/server';

import { loadClipWithPerms } from '@/lib/clipPerms';
import { validateVlmReview } from '@/lib/labelingV2';
import { supabaseAdmin } from '@/lib/supabase';
import { databaseError, loadOwnSession } from '../../_helpers';

export const runtime = 'nodejs';

export async function POST(
  req: NextRequest,
  { params }: { params: { clipId: string } },
) {
  const accessResult = await loadClipWithPerms(req, params.clipId);
  if (!accessResult.ok) return accessResult.response;

  let review;
  try {
    review = validateVlmReview(await req.json());
  } catch (error) {
    return NextResponse.json(
      { detail: (error as Error).message },
      { status: 400 },
    );
  }

  try {
    const session = await loadOwnSession(
      params.clipId,
      accessResult.access.userId,
    );
    if (!session?.initial_gt || !session.prediction_snapshot) {
      return NextResponse.json(
        { detail: '먼저 blind GT를 잠그고 VLM 판정을 공개해야 해.' },
        { status: 409 },
      );
    }

    const now = new Date().toISOString();
    const { data, error } = await supabaseAdmin
      .from('clip_labeling_sessions')
      .update({
        stage: 'completed',
        vlm_verdict: review.verdict,
        vlm_error_tags: review.error_tags,
        vlm_review_note: review.note,
        completion_reason: 'vlm_reviewed',
        completed_at: now,
        updated_at: now,
      })
      .eq('id', session.id)
      .select('*')
      .single();
    if (error) throw new Error(error.message);
    return NextResponse.json({ session: data });
  } catch (error) {
    return databaseError(error);
  }
}
