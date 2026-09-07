import 'server-only';

import { NextRequest, NextResponse } from 'next/server';

import { isOwnerId } from '@/lib/clipPerms';
import { requireLabelingAccess } from '@/lib/labelingAccess';
import { isProductionLabelingMedia } from '@/lib/motionClipPurpose';
import { supabaseAdmin } from '@/lib/supabase';

// DB 가드(fn_is_motion_clip_production_labeling_eligible)와 같은 제외 상태. 격리·삭제 clip 은 없는 것으로 본다.
const EXCLUDED_STATES = ['quarantined', 'media_deleted'] as const;

export interface V4ClipRow {
  id: string;
  camera_id: string | null;
  started_at: string;
  duration_sec: number | null;
  r2_key: string | null;
  clip_purpose: string | null;
}

export type V4ClipAccess =
  | { ok: true; userId: string; isOwner: boolean; clip: V4ClipRow }
  | { ok: false; response: NextResponse };

import { isUuid } from '@/lib/uuid';

export { isUuid };

function notFound(): NextResponse {
  return NextResponse.json({ detail: '영상을 찾을 수 없어.', code: 'not_found' }, { status: 404 });
}

// 격리·삭제된 clip 인가. isMotionMediaDeleted(labelingV3Server) 와 같은 테이블, 상태만 둘로 넓힌다.
export async function isMotionClipExcluded(clipId: string): Promise<boolean> {
  const { data, error } = await supabaseAdmin
    .from('motion_clip_system_exclusions')
    .select('state')
    .eq('clip_id', clipId)
    .in('state', [...EXCLUDED_STATES])
    .limit(1);
  if (error) throw error;
  return (data ?? []).length > 0;
}

// 승인 사용자(owner 또는 labelers row)면 어떤 clip 이든 읽을 수 있다(v4 스펙 §4.1: 배정은 권한이 아님).
// 단 운영 적격(production 목적 + canonical R2 경로 + 격리/삭제 아님)이 아닌 clip 은 미존재와 같은 404 —
// DB 가드와 별개인 API 계층의 2차 fail-closed 방어이며 존재 여부를 새지 않는다.
export async function loadV4ClipAccess(req: NextRequest, clipId: string): Promise<V4ClipAccess> {
  if (!isUuid(clipId)) {
    return { ok: false, response: NextResponse.json({ detail: '잘못된 영상 id 야.', code: 'invalid_request' }, { status: 400 }) };
  }
  const access = await requireLabelingAccess(req);
  if (!access.ok) return access;
  const { data, error } = await supabaseAdmin
    .from('motion_clips')
    .select('id, camera_id, started_at, duration_sec, r2_key, clip_purpose')
    .eq('id', clipId)
    .limit(1);
  if (error) throw error;
  const clip = (data ?? [])[0] as V4ClipRow | undefined;
  if (!clip) return { ok: false, response: notFound() };
  if (!isProductionLabelingMedia(clip.clip_purpose, clip.r2_key)) return { ok: false, response: notFound() };
  if (await isMotionClipExcluded(clip.id)) return { ok: false, response: notFound() };
  return { ok: true, userId: access.userId, isOwner: access.isOwner, clip };
}

// 표시명 단일 resolver — owner 는 'Owner', 아니면 labeler_applications.display_name, 없으면 '라벨러'.
// SQL 은 raw(nullable) 만 돌려주고 이 함수만 문자열을 정한다(F7).
export function resolveReviewerName({ reviewerId, displayName }: { reviewerId: string; displayName: string | null }): string {
  if (isOwnerId(reviewerId)) return 'Owner';
  return displayName ?? '라벨러';
}

// 여러 reviewer 의 raw 표시명을 한 번의 쿼리로. 없는 사용자는 null 로 채운다(resolver 가 기본값을 정함).
export async function loadReviewerDisplayNames(ids: string[]): Promise<Map<string, string | null>> {
  const unique = Array.from(new Set(ids));
  const names = new Map<string, string | null>(unique.map((id) => [id, null]));
  if (unique.length === 0) return names;
  const { data, error } = await supabaseAdmin
    .from('labeler_applications')
    .select('user_id, display_name')
    .in('user_id', unique);
  if (error) throw error;
  for (const row of (data ?? []) as { user_id?: unknown; display_name?: unknown }[]) {
    if (typeof row.user_id === 'string' && names.has(row.user_id)) {
      names.set(row.user_id, typeof row.display_name === 'string' ? row.display_name : null);
    }
  }
  return names;
}
