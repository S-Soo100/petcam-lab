import 'server-only';

import { NextRequest, NextResponse } from 'next/server';
import { supabaseAdmin } from '@/lib/supabase';
import { verifyBearer } from '@/lib/clipPerms';
import { databaseUnavailable } from '@/lib/apiErrors';

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
    // 내부 Supabase 메시지를 숨기고 일반 502(서버 로그에만 기록).
    return { ok: false, response: databaseUnavailable('router reviewer lookup', error) };
  }
  if ((data ?? []).length === 0) {
    return {
      ok: false,
      response: NextResponse.json({ detail: 'forbidden' }, { status: 403 }),
    };
  }
  // (예전의 튜토리얼 완료 production 게이트는 트랙 퇴역(2026-09-07 owner 결정)으로 제거 —
  // labelers 멤버십만 본다.)
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
