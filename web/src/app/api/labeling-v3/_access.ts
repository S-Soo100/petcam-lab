import 'server-only';

import { NextRequest, NextResponse } from 'next/server';

import { requireOwner } from '@/lib/labelingAccess';
import type { MotionSessionRow } from '@/lib/labelingV3Server';
import { supabaseAdmin } from '@/lib/supabase';

// motion_clips v3 읽기 라우트(상세·미디어)가 공유하는 접근 판정 — 보안 크리티컬 단일 소스.
//
// 계약(설계 §10·§12, review-fix P0-2):
// - Owner 전용(requireOwner). owner(DEV_USER_ID)는 모든 운영 clip 접근, clip 소유 여부를 따지지
//   않는다. 라벨러의 유일한 열람/write 흐름은 /labeling/blind/** 뿐이다.
// - 라벨러 요청은 requireOwner 가 bearer 검증 + DEV_USER_ID env 비교만으로 403 을 돌려준다
//   (labelers/tutorial DB 조회 0, clip/triage/session DB 조회 0 — 과거 정답 우회 열람 차단).
// - 인증 실패=verifyBearer 응답, DEV_USER_ID 누락=503, 라벨러=403,
//   clip 없음=404, 잘못된 UUID=400, DB 오류=throw(라우트가 502 로 접음).
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
      stateUpdatedAt: string | null;
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
  // review-fix P0-2 후속: motion v3 직접 상세·미디어는 Owner 전용(requireOwner). 라벨러 요청은
  // labelers/tutorial DB 조회 없이 bearer + DEV_USER_ID env 비교만으로 403 으로 끝난다.
  const owner = await requireOwner(req);
  if (!owner.ok) return { ok: false, response: owner.response };
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
      .select('owner_decision, updated_at')
      .eq('clip_id', clipId)
      .limit(1),
    supabaseAdmin
      .from('motion_clip_labeling_sessions')
      .select(SESSION_COLUMNS)
      .eq('clip_id', clipId)
      .eq('reviewed_by', owner.userId)
      .limit(1),
  ]);
  if (triageRes.error) throw triageRes.error;
  if (sessionRes.error) throw sessionRes.error;

  const triageRow = (triageRes.data ?? [])[0] as
    | { owner_decision?: string | null; updated_at?: string | null }
    | undefined;
  const ownerDecision = triageRow?.owner_decision ?? null;
  const stateUpdatedAt = triageRow?.updated_at ?? null;
  // SESSION_COLUMNS 를 문자열로 조립해 supabase 가 row 타입을 추론하지 못하므로 unknown 경유 캐스트.
  const session =
    ((sessionRes.data ?? [])[0] as unknown as MotionSessionRow | undefined) ?? null;

  const clip: MotionClipRow = {
    id: raw.id as string,
    camera_id: raw.camera_id as string,
    camera_name: pickCameraName(raw.cameras as Parameters<typeof pickCameraName>[0]),
    started_at: raw.started_at as string,
    duration_sec: Number(raw.duration_sec),
    r2_key: (raw.r2_key as string | null) ?? null,
  };
  return {
    ok: true,
    userId: owner.userId,
    isOwner: true,
    clip,
    ownerDecision,
    stateUpdatedAt,
    session,
  };
}
