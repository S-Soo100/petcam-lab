import { randomUUID } from 'node:crypto';

import { NextRequest, NextResponse } from 'next/server';

import { loadCurrentGmeOverlaySource } from '@/lib/gmeOverlayServer';
import { supabaseAdmin } from '@/lib/supabase';
import { loadBlindSlotAccess } from '../../_access';

export const runtime = 'nodejs';

function response(detail: string, code: string, status: number): NextResponse {
  return NextResponse.json({ detail, code }, { status });
}

function mapRpcError(error: { code?: string } | null): NextResponse {
  if (error?.code === 'PT409') return response('화면의 GME 결과가 갱신됐어. 새로고침 후 다시 눌러줘.', 'overlay_changed', 409);
  if (error?.code === 'PT403') return response('대상을 찾을 수 없어.', 'not_assigned', 404);
  if (error?.code === 'PT427') return response('검증 링크가 만료됐어.', 'cohort_closed', 410);
  return response('미탐 기록 저장에 실패했어. 잠시 후 다시 시도해.', 'save_failed', 502);
}

export async function POST(req: NextRequest, { params }: { params: { clipId: string } }) {
  const cohortId = req.nextUrl.searchParams.get('cohort_id');
  const access = await loadBlindSlotAccess(req, params.clipId, cohortId);
  if (!access.ok) return access.response;

  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return response('요청 형식이 잘못됐어.', 'invalid_request', 400);
  }
  if (body === null || typeof body !== 'object' || Array.isArray(body)) {
    return response('요청 형식이 잘못됐어.', 'invalid_request', 400);
  }
  const input = body as Record<string, unknown>;
  const timestamp = input.timestamp_sec;
  const revision = input.overlay_revision;
  if (
    typeof timestamp !== 'number'
    || !Number.isFinite(timestamp)
    || timestamp < 0
    || timestamp > access.clip.duration_sec + 0.001
    || typeof revision !== 'string'
    || !/^[0-9a-f]{64}$/.test(revision)
  ) {
    return response('영상 시각 또는 GME 버전이 잘못됐어.', 'invalid_request', 400);
  }

  let source;
  try {
    source = await loadCurrentGmeOverlaySource(params.clipId);
  } catch (cause) {
    console.error('[blind-review] current GME lookup failed', cause);
    return response('현재 GME 결과를 확인하지 못했어.', 'save_failed', 502);
  }
  if (!source || source.overlayRevision !== revision) {
    return response('화면의 GME 결과가 갱신됐어. 새로고침 후 다시 눌러줘.', 'overlay_changed', 409);
  }

  const roundedTimestamp = Math.round(timestamp * 1000) / 1000;
  const { data, error } = await supabaseAdmin.rpc('fn_append_motion_clip_gme_miss', {
    p_event_id: randomUUID(),
    p_clip_id: params.clipId,
    p_reviewer_id: access.userId,
    p_cohort_kind: access.scope.cohortKind,
    p_cohort_id: access.scope.cohortId,
    p_gme_run_id: source.runId,
    p_overlay_revision: source.overlayRevision,
    p_timestamp_sec: roundedTimestamp,
  });
  if (error) return mapRpcError(error);
  const row = (Array.isArray(data) ? data[0] : data) as
    | { event_id?: string; timestamp_sec?: number; status?: string }
    | null;
  if (!row || row.status !== 'recorded') return mapRpcError(null);
  return NextResponse.json({
    status: 'recorded',
    timestamp_sec: Number(row.timestamp_sec),
  });
}
