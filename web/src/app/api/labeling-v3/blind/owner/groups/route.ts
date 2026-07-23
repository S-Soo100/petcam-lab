import { NextRequest, NextResponse } from 'next/server';

import { requireOwner } from '@/lib/labelingAccess';
import { supabaseAdmin } from '@/lib/supabase';
import {
  blindBadRequest,
  blindDatabaseError,
  blindRpcErrorResponse,
  isValidUuid,
} from '@/lib/motionBlindReviewServer';

export const runtime = 'nodejs';

// POST /api/labeling-v3/blind/owner/groups — 그룹/멤버/카메라 배정(설계 §2·§6). owner 전용.
// approved user_id 두 명 + 카메라. email 은 저장 key 로 받지 않고(UUID 만), 응답에도 담지 않는다.
// RPC 가 approved labeler 2인·카메라 중복을 강제한다(PT425).
const MAX_BODY_BYTES = 64 * 1024;
const ALLOWED = new Set(['group_id', 'name', 'member_ids', 'camera_ids']);

function allUuids(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((v) => typeof v === 'string' && isValidUuid(v));
}

export async function POST(req: NextRequest) {
  const owner = await requireOwner(req);
  if (!owner.ok) return owner.response;

  const declared = req.headers.get('content-length');
  if (declared && Number(declared) > MAX_BODY_BYTES) {
    return NextResponse.json({ detail: '요청이 너무 커.', code: 'payload_too_large' }, { status: 413 });
  }
  let raw: string;
  try {
    raw = await req.text();
  } catch {
    return blindBadRequest('본문을 읽을 수 없어.');
  }
  if (Buffer.byteLength(raw, 'utf8') > MAX_BODY_BYTES) {
    return NextResponse.json({ detail: '요청이 너무 커.', code: 'payload_too_large' }, { status: 413 });
  }
  let body: Record<string, unknown>;
  try {
    const parsed = JSON.parse(raw || '{}');
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) return blindBadRequest('본문이 올바르지 않아.');
    body = parsed as Record<string, unknown>;
  } catch {
    return blindBadRequest('본문이 올바르지 않아.');
  }
  for (const k of Object.keys(body)) if (!ALLOWED.has(k)) return blindBadRequest('허용되지 않은 필드가 있어.');

  const name = body.name;
  if (typeof name !== 'string' || name.trim().length < 1 || name.trim().length > 80) {
    return blindBadRequest('그룹 이름이 올바르지 않아.');
  }
  if (!allUuids(body.member_ids) || (body.member_ids as string[]).length !== 2) {
    return blindBadRequest('승인된 라벨러 두 명을 골라줘.');
  }
  if (!allUuids(body.camera_ids) || (body.camera_ids as string[]).length < 1 || (body.camera_ids as string[]).length > 20) {
    return blindBadRequest('카메라를 1~20대 골라줘.');
  }
  const groupId = body.group_id == null ? null : body.group_id;
  if (groupId !== null && (typeof groupId !== 'string' || !isValidUuid(groupId))) {
    return blindBadRequest('그룹 id 가 올바르지 않아.');
  }

  try {
    const { data, error } = await supabaseAdmin.rpc('fn_manage_motion_review_group', {
      p_group_id: groupId,
      p_actor_id: owner.userId,
      p_name: name,
      p_member_ids: body.member_ids,
      p_camera_ids: body.camera_ids,
    });
    if (error) return blindRpcErrorResponse(error) ?? blindDatabaseError(error);
    const resolved = (Array.isArray(data) ? data[0] : data) as string | { fn_manage_motion_review_group?: string };
    const id = typeof resolved === 'string' ? resolved : resolved?.fn_manage_motion_review_group ?? null;
    return NextResponse.json({ group_id: id });
  } catch (cause) {
    return blindDatabaseError(cause);
  }
}
