import { NextRequest, NextResponse } from 'next/server';
import { supabaseAdmin } from '@/lib/supabase';
import { loadClipWithPerms } from '@/lib/clipPerms';
import {
  attachOwnLabels,
  loadOwnLabelsByItemId,
  verifyRouterReviewer,
} from '../../_helpers';

export const runtime = 'nodejs';

export async function GET(
  req: NextRequest,
  { params }: { params: { clipId: string } },
) {
  const reviewerResult = await verifyRouterReviewer(req);
  if (!reviewerResult.ok) return reviewerResult.response;
  const { userId } = reviewerResult.reviewer;

  const batchId = req.nextUrl.searchParams.get('batch_id') || 'router-eval-v1-20260710';
  const clipAccess = await loadClipWithPerms(req, params.clipId);
  if (!clipAccess.ok) return clipAccess.response;

  const { data: itemRows, error } = await supabaseAdmin
    .from('router_review_items')
    .select('*')
    .eq('batch_id', batchId)
    .eq('clip_id', params.clipId)
    .limit(1);
  if (error) {
    return NextResponse.json(
      { detail: `supabase error: ${error.message}` },
      { status: 502 },
    );
  }
  const item = (itemRows ?? [])[0];
  if (!item) {
    return NextResponse.json({ detail: 'review item not found' }, { status: 404 });
  }

  let labels: Record<string, unknown>;
  try {
    labels = await loadOwnLabelsByItemId([String(item.id)], userId);
  } catch (e) {
    return NextResponse.json(
      { detail: `supabase error: ${(e as Error).message}` },
      { status: 502 },
    );
  }
  const joinedItem = attachOwnLabels([item], labels)[0];

  const { data: batchItems, error: batchErr } = await supabaseAdmin
    .from('router_review_items')
    .select('id,clip_id,sample_group,started_at')
    .eq('batch_id', batchId)
    .order('sample_group', { ascending: true })
    .order('started_at', { ascending: true });
  if (batchErr) {
    return NextResponse.json(
      { detail: `supabase error: ${batchErr.message}` },
      { status: 502 },
    );
  }
  const allItems = batchItems ?? [];
  const allLabels = await loadOwnLabelsByItemId(
    allItems.map((row) => String(row.id)),
    userId,
  );
  const next = allItems.find((row) => !allLabels[String(row.id)] && row.clip_id !== params.clipId);

  return NextResponse.json({
    item: joinedItem,
    clip: clipAccess.access.clip,
    next_unreviewed_clip_id: next?.clip_id ?? null,
  });
}
