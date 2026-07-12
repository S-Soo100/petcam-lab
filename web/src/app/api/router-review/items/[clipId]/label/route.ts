import { NextRequest, NextResponse } from 'next/server';
import { supabaseAdmin } from '@/lib/supabase';
import { loadClipWithPerms } from '@/lib/clipPerms';
import { verifyRouterReviewer } from '../../../_helpers';

export const runtime = 'nodejs';

const VISIBLE = new Set(['yes', 'no', 'unclear']);
const ACTIONS = new Set([
  'moving',
  'static',
  'feeding',
  'drinking',
  'hidden',
  'unseen',
  'human_noise',
  'other',
]);
const OK = new Set(['yes', 'no', 'unclear']);

export async function POST(
  req: NextRequest,
  { params }: { params: { clipId: string } },
) {
  const reviewerResult = await verifyRouterReviewer(req);
  if (!reviewerResult.ok) return reviewerResult.response;
  const { userId } = reviewerResult.reviewer;

  const clipAccess = await loadClipWithPerms(req, params.clipId);
  if (!clipAccess.ok) return clipAccess.response;

  const batchId = req.nextUrl.searchParams.get('batch_id') || 'router-eval-v1-20260710';
  const body = await req.json().catch(() => null);
  if (!body || typeof body !== 'object') {
    return NextResponse.json({ detail: 'invalid json body' }, { status: 400 });
  }

  const manualVisibleGecko = String(body.manual_visible_gecko ?? '');
  const manualActionGt = String(body.manual_action_gt ?? '');
  const manualRouterOk = String(body.manual_router_ok ?? '');
  if (!VISIBLE.has(manualVisibleGecko)) {
    return NextResponse.json({ detail: 'manual_visible_gecko invalid' }, { status: 400 });
  }
  if (!ACTIONS.has(manualActionGt)) {
    return NextResponse.json({ detail: 'manual_action_gt invalid' }, { status: 400 });
  }
  if (!OK.has(manualRouterOk)) {
    return NextResponse.json({ detail: 'manual_router_ok invalid' }, { status: 400 });
  }

  const { data: itemRows, error: itemErr } = await supabaseAdmin
    .from('router_review_items')
    .select('id,clip_id')
    .eq('batch_id', batchId)
    .eq('clip_id', params.clipId)
    .limit(1);
  if (itemErr) {
    return NextResponse.json(
      { detail: `supabase error: ${itemErr.message}` },
      { status: 502 },
    );
  }
  const item = (itemRows ?? [])[0];
  if (!item) {
    return NextResponse.json({ detail: 'review item not found' }, { status: 404 });
  }

  const payload = {
    review_item_id: item.id,
    clip_id: params.clipId,
    reviewed_by: userId,
    manual_visible_gecko: manualVisibleGecko,
    manual_action_gt: manualActionGt,
    manual_router_ok: manualRouterOk,
    manual_notes:
      typeof body.manual_notes === 'string' && body.manual_notes.trim()
        ? body.manual_notes.trim()
        : null,
    reviewed_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };

  const { data, error } = await supabaseAdmin
    .from('router_review_labels')
    .upsert(payload, { onConflict: 'review_item_id,reviewed_by' })
    .select('*')
    .single();
  if (error) {
    return NextResponse.json(
      { detail: `supabase error: ${error.message}` },
      { status: 502 },
    );
  }
  return NextResponse.json(data);
}
