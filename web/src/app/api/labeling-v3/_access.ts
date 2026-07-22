import 'server-only';

import { NextRequest, NextResponse } from 'next/server';

import { requireProductionLabelingAccess } from '@/lib/labelingAccess';
import type { MotionSessionRow } from '@/lib/labelingV3Server';
import { supabaseAdmin } from '@/lib/supabase';

// motion_clips v3 읽기 라우트(상세·미디어)가 공유하는 접근 판정 — 보안 크리티컬 단일 소스.
//
// 계약(설계 §10·§12):
// - owner(DEV_USER_ID): 모든 운영 clip 접근. clip 소유 여부를 따지지 않는다.
// - labeler: owner_decision='label' 이거나 본인 세션이 있는 clip 만(진행 중 세션 보호).
//   그 외에는 clip 존재를 드러내지 않는 404 를 준다.
// - clip 없음=404, 잘못된 UUID=400, DB 오류=throw(라우트가 502 로 접음).
// 미디어 URL 은 여기서 발급하지 않는다(r2_key 만 넘기고 서명은 미디어 라우트가 한다).

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const SESSION_COLUMNS =
  'stage, initial_gt, current_gt, prediction_snapshot, vlm_verdict, ' +
  'vlm_error_tags, vlm_review_note, completion_reason, gt_locked_at, completed_at';

export interface MotionClipRow {
  id: string;
  camera_id: string;
  camera_name: string | null;
  started_at: string;
  duration_sec: number;
  r2_key: string | null;
}

export type MotionClipAccess =
  | {
      ok: true;
      userId: string;
      isOwner: boolean;
      clip: MotionClipRow;
      ownerDecision: string | null;
      session: MotionSessionRow | null;
    }
  | { ok: false; response: NextResponse };

function notFound(): NextResponse {
  return NextResponse.json({ detail: '대상을 찾을 수 없어.', code: 'not_found' }, { status: 404 });
}

// PostgREST to-one embed 는 object 이지만 배열로 오는 경우도 방어한다.
function pickCameraName(
  cameras: { name?: string | null } | { name?: string | null }[] | null | undefined,
): string | null {
  if (Array.isArray(cameras)) return cameras[0]?.name ?? null;
  return cameras?.name ?? null;
}

export async function loadMotionClipAccess(
  req: NextRequest,
  clipId: string,
): Promise<MotionClipAccess> {
  const access = await requireProductionLabelingAccess(req);
  if (!access.ok) return { ok: false, response: access.response };
  if (!UUID.test(clipId)) {
    return {
      ok: false,
      response: NextResponse.json({ detail: '잘못된 clip id', code: 'invalid_request' }, { status: 400 }),
    };
  }

  const { data: clipData, error: clipErr } = await supabaseAdmin
    .from('motion_clips')
    .select('id, camera_id, started_at, duration_sec, r2_key, cameras(name)')
    .eq('id', clipId)
    .limit(1);
  if (clipErr) throw clipErr;
  const raw = (clipData ?? [])[0] as
    | (Record<string, unknown> & { cameras?: unknown })
    | undefined;
  if (!raw) return { ok: false, response: notFound() };

  // triage 상태(state)와 본인 세션을 함께 읽는다 — 상세 구성 + labeler 접근 판정 공용.
  const [triageRes, sessionRes] = await Promise.all([
    supabaseAdmin
      .from('motion_clip_labeling_triage')
      .select('owner_decision')
      .eq('clip_id', clipId)
      .limit(1),
    supabaseAdmin
      .from('motion_clip_labeling_sessions')
      .select(SESSION_COLUMNS)
      .eq('clip_id', clipId)
      .eq('reviewed_by', access.userId)
      .limit(1),
  ]);
  if (triageRes.error) throw triageRes.error;
  if (sessionRes.error) throw sessionRes.error;

  const ownerDecision =
    ((triageRes.data ?? [])[0]?.owner_decision as string | null | undefined) ?? null;
  // SESSION_COLUMNS 를 문자열로 조립해 supabase 가 row 타입을 추론하지 못하므로 unknown 경유 캐스트.
  const session =
    ((sessionRes.data ?? [])[0] as unknown as MotionSessionRow | undefined) ?? null;

  // labeler 접근 은닉: label 도 아니고 본인 세션도 없으면 존재 자체를 드러내지 않는다.
  if (!access.isOwner && ownerDecision !== 'label' && !session) {
    return { ok: false, response: notFound() };
  }

  const clip: MotionClipRow = {
    id: raw.id as string,
    camera_id: raw.camera_id as string,
    camera_name: pickCameraName(raw.cameras as Parameters<typeof pickCameraName>[0]),
    started_at: raw.started_at as string,
    duration_sec: Number(raw.duration_sec),
    r2_key: (raw.r2_key as string | null) ?? null,
  };
  return { ok: true, userId: access.userId, isOwner: access.isOwner, clip, ownerDecision, session };
}
