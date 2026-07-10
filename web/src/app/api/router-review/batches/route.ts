import { NextRequest, NextResponse } from 'next/server';
import { supabaseAdmin } from '@/lib/supabase';
import { verifyRouterReviewer, loadOwnLabelsByItemId } from '../_helpers';

export const runtime = 'nodejs';

export async function GET(req: NextRequest) {
  const reviewerResult = await verifyRouterReviewer(req);
  if (!reviewerResult.ok) return reviewerResult.response;
  const { userId } = reviewerResult.reviewer;

  const { data, error } = await supabaseAdmin
    .from('router_review_items')
    .select('id,batch_id')
    .order('batch_id', { ascending: false });
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

  const byBatch = new Map<string, { count: number; reviewed_count: number }>();
  for (const item of items) {
    const batchId = String(item.batch_id);
    const current = byBatch.get(batchId) ?? { count: 0, reviewed_count: 0 };
    current.count += 1;
    if (labels[String(item.id)]) current.reviewed_count += 1;
    byBatch.set(batchId, current);
  }

  return NextResponse.json(
    Array.from(byBatch.entries()).map(([batch_id, counts]) => ({
      batch_id,
      ...counts,
    })),
  );
}
