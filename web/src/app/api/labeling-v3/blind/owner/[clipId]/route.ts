import { NextRequest, NextResponse } from 'next/server';

import { requireOwner } from '@/lib/labelingAccess';
import { supabaseAdmin } from '@/lib/supabase';
import {
  blindBadRequest,
  blindDatabaseError,
  isValidUuid,
  mapOwnerSubmission,
  type OwnerSubmissionRow,
} from '@/lib/motionBlindReviewServer';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

// GET /api/labeling-v3/blind/owner/[clipId] — 두 최초 제출 side-by-side(설계 §4.5). owner 전용.
// auth UUID·digest·slot·r2_key 는 담지 않는다. optimistic concurrency 용 updated_at 을 함께 준다.
function pickCameraName(cameras: { name?: string | null } | { name?: string | null }[] | null | undefined): string | null {
  if (Array.isArray(cameras)) return cameras[0]?.name ?? null;
  return cameras?.name ?? null;
}

export async function GET(req: NextRequest, { params }: { params: { clipId: string } }) {
  const owner = await requireOwner(req);
  if (!owner.ok) return owner.response;
  if (!isValidUuid(params.clipId)) return blindBadRequest('잘못된 clip id');

  try {
    const { data: consData, error: consErr } = await supabaseAdmin
      .from('motion_clip_consensus')
      .select('status, differing_fields, submission_a, submission_b, updated_at, final_decision')
      .eq('clip_id', params.clipId)
      .eq('cohort_kind', 'live')
      .limit(1);
    if (consErr) throw consErr;
    const consensus = (consData ?? [])[0] as
      | {
          status: string;
          differing_fields: string[] | null;
          submission_a: string | null;
          submission_b: string | null;
          updated_at: string;
          final_decision: string | null;
        }
      | undefined;
    if (!consensus) {
      return NextResponse.json({ detail: '대상을 찾을 수 없어.', code: 'not_found' }, { status: 404 });
    }

    const ids = [consensus.submission_a, consensus.submission_b].filter(Boolean) as string[];
    const { data: subData, error: subErr } = await supabaseAdmin
      .from('motion_clip_blind_submissions')
      .select('id, decision, reason_code, initial_gt, note')
      .in('id', ids);
    if (subErr) throw subErr;
    const byId = new Map((subData ?? []).map((r) => [(r as { id: string }).id, r as OwnerSubmissionRow]));

    const { data: clipData, error: clipErr } = await supabaseAdmin
      .from('motion_clips')
      .select('id, started_at, duration_sec, r2_key, cameras(name)')
      .eq('id', params.clipId)
      .limit(1);
    if (clipErr) throw clipErr;
    const raw = (clipData ?? [])[0] as (Record<string, unknown> & { cameras?: unknown }) | undefined;

    return NextResponse.json({
      clip: raw
        ? {
            id: raw.id as string,
            camera_name: pickCameraName(raw.cameras as Parameters<typeof pickCameraName>[0]) ?? '이름 없는 카메라',
            started_at: raw.started_at as string,
            duration_sec: Number(raw.duration_sec),
            media_ready: (raw.r2_key as string | null) != null,
          }
        : null,
      status: consensus.status,
      differing_fields: Array.isArray(consensus.differing_fields) ? consensus.differing_fields : [],
      updated_at: consensus.updated_at,
      submission_a: mapOwnerSubmission(consensus.submission_a ? byId.get(consensus.submission_a) ?? null : null),
      submission_b: mapOwnerSubmission(consensus.submission_b ? byId.get(consensus.submission_b) ?? null : null),
    });
  } catch (cause) {
    return blindDatabaseError(cause);
  }
}
