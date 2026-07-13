import 'server-only';

import { NextRequest, NextResponse } from 'next/server';
import { supabaseAdmin } from '@/lib/supabase';
import { verifyBearer } from '@/lib/clipPerms';

export interface RouterReviewer {
  userId: string;
}

export type RouterReviewerResult =
  | { ok: true; reviewer: RouterReviewer }
  | { ok: false; response: NextResponse };

export async function verifyRouterReviewer(
  req: NextRequest,
): Promise<RouterReviewerResult> {
  const authResult = await verifyBearer(req);
  if (!authResult.ok) return authResult;
  const { userId } = authResult.auth;

  const devUserId = process.env.DEV_USER_ID;
  if (devUserId && userId === devUserId) {
    return { ok: true, reviewer: { userId } };
  }

  const { data, error } = await supabaseAdmin
    .from('labelers')
    .select('user_id')
    .eq('user_id', userId)
    .limit(1);
  if (error) {
    return {
      ok: false,
      response: NextResponse.json(
        { detail: `supabase error: ${error.message}` },
        { status: 502 },
      ),
    };
  }
  if ((data ?? []).length === 0) {
    return {
      ok: false,
      response: NextResponse.json({ detail: 'forbidden' }, { status: 403 }),
    };
  }
  // production 게이트 — 미완료 labeler 는 라우터 리뷰(일반 clip 열람)도 차단(설계 §12).
  // owner 는 위 devUserId 분기에서 이미 통과했으므로 여기 도달하지 않는다.
  const { tutorialGateResponse } = await import('@/lib/labelingTutorialGate');
  const blocked = await tutorialGateResponse(userId);
  if (blocked) return { ok: false, response: blocked };
  return { ok: true, reviewer: { userId } };
}

export function attachOwnLabels<T extends { id: string }>(
  items: T[],
  labels: Record<string, unknown>,
) {
  return items.map((item) => ({
    ...item,
    label: labels[item.id] ?? null,
  }));
}

export async function loadOwnLabelsByItemId(
  itemIds: string[],
  userId: string,
): Promise<Record<string, unknown>> {
  if (itemIds.length === 0) return {};
  const { data, error } = await supabaseAdmin
    .from('router_review_labels')
    .select('*')
    .in('review_item_id', itemIds)
    .eq('reviewed_by', userId);
  if (error) {
    throw new Error(error.message);
  }
  const out: Record<string, unknown> = {};
  for (const row of data ?? []) {
    out[String(row.review_item_id)] = row;
  }
  return out;
}
