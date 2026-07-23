import 'server-only';

import { NextRequest, NextResponse } from 'next/server';

import { supabaseAdmin } from '@/lib/supabase';
import {
  isValidUuid,
  requireBlindLabeler,
  type BlindClipDetailRow,
} from '@/lib/motionBlindReviewServer';

// 블라인드 read 라우트(상세·미디어)가 공유하는 slot 인가 — 보안 크리티컬 단일 소스.
//
// 계약(설계 §5·§7):
// - reviewer id 는 bearer access 에서만. body/query 를 신뢰하지 않는다.
// - 본인 slot(clip×reviewer×cohort scope)이 있을 때만 접근. 없으면 존재를 드러내지 않는 404.
// - canary 는 cohort 가 open·kind=canary 일 때만. 닫힌/미존재 cohort 는 안전한 만료 상태.
// - 여기서 media URL 을 발급하지 않는다(r2_key 만 넘기고 서명은 미디어 라우트가 한다).
// - lease 를 만들지 않는다(GET detail 은 read-only, 설계 §7).

export interface BlindSlotScope {
  cohortKind: 'live' | 'canary';
  cohortId: string | null;
}

// 제출 라우트가 GT 를 실제 영상 길이로 검증하기 위한 배정 결과(하드닝: GT_DURATION_CAP 제거).
export interface AssignedBlindClip {
  clipId: string;
  durationSec: number;
  groupId: string;
  cohortKind: 'live' | 'canary';
  cohortId: string | null;
}

export interface BlindClipRow {
  id: string;
  camera_name: string | null;
  started_at: string;
  duration_sec: number;
  r2_key: string | null;
}

export type BlindSlotAccess =
  | {
      ok: true;
      userId: string;
      scope: BlindSlotScope;
      clip: BlindClipRow;
      detailRow: BlindClipDetailRow;
    }
  | { ok: false; response: NextResponse };

function badRequest(detail: string): NextResponse {
  return NextResponse.json({ detail, code: 'invalid_request' }, { status: 400 });
}

function notFound(): NextResponse {
  return NextResponse.json({ detail: '대상을 찾을 수 없어.', code: 'not_assigned' }, { status: 404 });
}

// cohort_id 없으면 live scope, 있으면 canary scope. 잘못된 UUID 는 null(400).
export function parseCohortScope(cohortId: string | null): BlindSlotScope | null {
  if (cohortId === null || cohortId === '') return { cohortKind: 'live', cohortId: null };
  if (!isValidUuid(cohortId)) return null;
  return { cohortKind: 'canary', cohortId };
}

function pickCameraName(
  cameras: { name?: string | null } | { name?: string | null }[] | null | undefined,
): string | null {
  if (Array.isArray(cameras)) return cameras[0]?.name ?? null;
  return cameras?.name ?? null;
}

export async function loadBlindSlotAccess(
  req: NextRequest,
  clipId: string,
  cohortId: string | null,
): Promise<BlindSlotAccess> {
  const access = await requireBlindLabeler(req);
  if (!access.ok) return { ok: false, response: access.response };
  if (!isValidUuid(clipId)) return { ok: false, response: badRequest('잘못된 clip id') };

  const scope = parseCohortScope(cohortId);
  if (!scope) return { ok: false, response: badRequest('잘못된 cohort id') };

  // canary 는 열린 cohort 만 노출한다(설계 §6.3). 닫힘/미존재 = 만료된 링크로 은닉.
  if (scope.cohortKind === 'canary') {
    const { data, error } = await supabaseAdmin
      .from('motion_blind_review_cohorts')
      .select('id, status, kind')
      .eq('id', scope.cohortId)
      .limit(1);
    if (error) throw error;
    const cohort = (data ?? [])[0] as { status?: string; kind?: string } | undefined;
    if (!cohort || cohort.status !== 'open' || cohort.kind !== 'canary') {
      return {
        ok: false,
        response: NextResponse.json(
          { detail: '검증 링크가 만료됐어.', code: 'cohort_closed' },
          { status: 410 },
        ),
      };
    }
  }

  // 본인 slot 인가(설계 §7). 상대 제출 필드는 select 하지 않는다.
  let slotQuery = supabaseAdmin
    .from('motion_clip_review_slots')
    .select('activity_day_kst, submitted_at, cohort_kind')
    .eq('clip_id', clipId)
    .eq('reviewer_id', access.userId)
    .eq('cohort_kind', scope.cohortKind);
  slotQuery = scope.cohortId
    ? slotQuery.eq('cohort_id', scope.cohortId)
    : slotQuery.is('cohort_id', null);
  const { data: slotData, error: slotErr } = await slotQuery.limit(1);
  if (slotErr) throw slotErr;
  const slot = (slotData ?? [])[0] as
    | { activity_day_kst: string; submitted_at: string | null; cohort_kind: string }
    | undefined;
  if (!slot) return { ok: false, response: notFound() };

  // slot 인가 후에만 clip media 를 읽는다(설계 §9). r2_key 는 응답에 담지 않는다.
  const { data: clipData, error: clipErr } = await supabaseAdmin
    .from('motion_clips')
    .select('id, started_at, duration_sec, r2_key, cameras(name)')
    .eq('id', clipId)
    .limit(1);
  if (clipErr) throw clipErr;
  const raw = (clipData ?? [])[0] as
    | (Record<string, unknown> & { cameras?: unknown })
    | undefined;
  if (!raw) return { ok: false, response: notFound() };

  const clip: BlindClipRow = {
    id: raw.id as string,
    camera_name: pickCameraName(raw.cameras as Parameters<typeof pickCameraName>[0]),
    started_at: raw.started_at as string,
    duration_sec: Number(raw.duration_sec),
    r2_key: (raw.r2_key as string | null) ?? null,
  };

  const detailRow: BlindClipDetailRow = {
    clip_id: clip.id,
    camera_name: clip.camera_name,
    started_at: clip.started_at,
    duration_sec: clip.duration_sec,
    media_ready: clip.r2_key != null,
    activity_day_kst: slot.activity_day_kst,
    cohort_kind: slot.cohort_kind,
    own_submitted: slot.submitted_at != null,
  };

  return { ok: true, userId: access.userId, scope, clip, detailRow };
}

// 제출 배정 확인(하드닝) — 이미 인증된 reviewer(userId) 기준으로 본인 slot 을 먼저 확인하고,
// 그 뒤에만 실제 clip duration 을 읽어 반환한다. 미배정·잘못된 cohort·닫힌 canary·미존재 clip 은
// 모두 null 로 일반화해 존재를 드러내지 않는다(설계 §7·§9). 상대 제출 필드는 절대 select 하지 않는다.
export async function getAssignedBlindClip(
  userId: string,
  clipId: string,
  scope: BlindSlotScope,
): Promise<AssignedBlindClip | null> {
  // canary 는 열린 cohort 만(설계 §6.3). 닫힘/미존재 = not_assigned 로 일반화.
  if (scope.cohortKind === 'canary') {
    const { data, error } = await supabaseAdmin
      .from('motion_blind_review_cohorts')
      .select('id, status, kind')
      .eq('id', scope.cohortId)
      .limit(1);
    if (error) throw error;
    const cohort = (data ?? [])[0] as { status?: string; kind?: string } | undefined;
    if (!cohort || cohort.status !== 'open' || cohort.kind !== 'canary') return null;
  }

  // 본인 slot 인가 먼저(설계 §7). 없으면 not_assigned. group_id 도 여기서 얻는다.
  let slotQuery = supabaseAdmin
    .from('motion_clip_review_slots')
    .select('group_id, cohort_kind')
    .eq('clip_id', clipId)
    .eq('reviewer_id', userId)
    .eq('cohort_kind', scope.cohortKind);
  slotQuery = scope.cohortId
    ? slotQuery.eq('cohort_id', scope.cohortId)
    : slotQuery.is('cohort_id', null);
  const { data: slotData, error: slotErr } = await slotQuery.limit(1);
  if (slotErr) throw slotErr;
  const slot = (slotData ?? [])[0] as { group_id: string } | undefined;
  if (!slot) return null;

  // slot 인가 후에만 clip duration 을 읽는다(존재 은닉 유지, 설계 §9).
  const { data: clipData, error: clipErr } = await supabaseAdmin
    .from('motion_clips')
    .select('id, duration_sec')
    .eq('id', clipId)
    .limit(1);
  if (clipErr) throw clipErr;
  const clip = (clipData ?? [])[0] as { id: string; duration_sec: number | string } | undefined;
  if (!clip) return null;

  return {
    clipId: clip.id,
    durationSec: Number(clip.duration_sec),
    groupId: slot.group_id,
    cohortKind: scope.cohortKind,
    cohortId: scope.cohortId,
  };
}

// owner 최종 판정용 clip duration(하드닝) — owner 는 전역 접근이라 slot 없이 clip 을 읽는다.
// requireOwner 성공 뒤에만 호출한다. GT 를 실제 영상 길이로 검증하기 위한 duration 만 반환.
export async function getOwnerClipDuration(clipId: string): Promise<number | null> {
  const { data, error } = await supabaseAdmin
    .from('motion_clips')
    .select('duration_sec')
    .eq('id', clipId)
    .limit(1);
  if (error) throw error;
  const clip = (data ?? [])[0] as { duration_sec: number | string } | undefined;
  if (!clip) return null;
  return Number(clip.duration_sec);
}
