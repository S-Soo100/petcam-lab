import { NextRequest, NextResponse } from 'next/server';
import { supabaseAdmin } from '@/lib/supabase';
import {
  attachOwnLabels,
  loadOwnLabelsByItemId,
  verifyRouterReviewer,
} from '../_helpers';

export const runtime = 'nodejs';

export async function GET(req: NextRequest) {
  const reviewerResult = await verifyRouterReviewer(req);
  if (!reviewerResult.ok) return reviewerResult.response;
  const { userId } = reviewerResult.reviewer;

  const sp = req.nextUrl.searchParams;
  const batchId = sp.get('batch_id') || 'router-eval-v1-20260710';
  const sampleGroup = sp.get('sample_group');
  const status = sp.get('status') || 'all';

  let query = supabaseAdmin
    .from('router_review_items')
    .select('*')
    .eq('batch_id', batchId)
    .order('sample_group', { ascending: true })
    .order('started_at', { ascending: true });
  if (sampleGroup) query = query.eq('sample_group', sampleGroup);

  const { data, error } = await query;
  if (error) {
    return NextResponse.json(
      { detail: `supabase error: ${error.message}` },
      { status: 502 },
    );
  }

  const items = data ?? [];
  let labels: Record<string, unknown>;
  try {
    labels = await loadOwnLabelsByItemId(
      items.map((item) => String(item.id)),
      userId,
    );
  } catch (e) {
    return NextResponse.json(
      { detail: `supabase error: ${(e as Error).message}` },
      { status: 502 },
    );
  }

  const joined = attachOwnLabels(items, labels);
  const filtered = joined.filter((item) => {
    if (status === 'reviewed') return item.label !== null;
    if (status === 'unreviewed') return item.label === null;
    return true;
  });

  return NextResponse.json({
    items: filtered,
    count: joined.length,
    reviewed_count: joined.filter((item) => item.label !== null).length,
  });
}
