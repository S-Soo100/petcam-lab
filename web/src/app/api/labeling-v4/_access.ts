import 'server-only';

import { NextRequest, NextResponse } from 'next/server';

import { requireLabelingAccess } from '@/lib/labelingAccess';
import { supabaseAdmin } from '@/lib/supabase';

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export interface V4ClipRow {
  id: string;
  camera_id: string | null;
  started_at: string;
  duration_sec: number | null;
  r2_key: string | null;
}

export type V4ClipAccess =
  | { ok: true; userId: string; isOwner: boolean; clip: V4ClipRow }
  | { ok: false; response: NextResponse };

export function isUuid(v: string): boolean {
  return UUID_RE.test(v);
}

// 승인 사용자(owner 또는 labelers row)면 어떤 clip 이든 읽을 수 있다(v4 스펙 §4.1: 배정은 권한이 아님).
export async function loadV4ClipAccess(req: NextRequest, clipId: string): Promise<V4ClipAccess> {
  if (!isUuid(clipId)) {
    return { ok: false, response: NextResponse.json({ detail: '잘못된 영상 id 야.', code: 'invalid_request' }, { status: 400 }) };
  }
  const access = await requireLabelingAccess(req);
  if (!access.ok) return access;
  const { data, error } = await supabaseAdmin
    .from('motion_clips')
    .select('id, camera_id, started_at, duration_sec, r2_key')
    .eq('id', clipId)
    .limit(1);
  if (error) throw error;
  const clip = (data ?? [])[0] as V4ClipRow | undefined;
  if (!clip) {
    return { ok: false, response: NextResponse.json({ detail: '영상을 찾을 수 없어.', code: 'not_found' }, { status: 404 }) };
  }
  return { ok: true, userId: access.userId, isOwner: access.isOwner, clip };
}

// 표시명: labeler_applications.display_name. owner 는 'Owner'. 없으면 '라벨러'.
export async function reviewerDisplayName(reviewerId: string | null): Promise<string | null> {
  if (!reviewerId) return null;
  if (process.env.DEV_USER_ID && reviewerId === process.env.DEV_USER_ID) return 'Owner';
  const { data, error } = await supabaseAdmin
    .from('labeler_applications')
    .select('display_name')
    .eq('user_id', reviewerId)
    .limit(1);
  if (error) throw error;
  return ((data ?? [])[0] as { display_name?: string } | undefined)?.display_name ?? '라벨러';
}
