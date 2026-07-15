import { NextRequest, NextResponse } from 'next/server';

import { requireOwner } from '@/lib/labelingAccess';
import { supabaseAdmin } from '@/lib/supabase';
import { databaseUnavailable } from '@/lib/apiErrors';
import { effectiveTriageState } from '@/lib/labelingTriage';
import {
  applyTriageClipFilters,
  applyTriageStateFilter,
  mapTriageRowToDetail,
  parseTriageClipFilters,
  type TriageJoinRow,
  type TriageListState,
} from '@/lib/labelingTriageServer';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const STATES = ['pending', 'skipped', 'labeled'] as const;
const DECISIONS = ['label', 'skip', 'reset'] as const;
type Decision = (typeof DECISIONS)[number];

const DETAIL_SELECT =
  'clip_id,suggested_route,suggestion_reason,suggestion_source,policy_version,' +
  'owner_decision,decided_at,decision_note,updated_at,' +
  'camera_clips!inner(id,camera_id,started_at,duration_sec,r2_key,thumbnail_r2_key)';

// GET /api/labeling-triage/[clipId]?state=pending&date_from=&date_to=&camera_id=
// owner-only 상세 + 같은 탭·같은 필터의 다음 clip. evidence_snapshot 미노출(설계 §8.2).
export async function GET(
  req: NextRequest,
  { params }: { params: { clipId: string } },
) {
  const owner = await requireOwner(req);
  if (!owner.ok) return owner.response;

  const clipId = params.clipId;
  if (!UUID_RE.test(clipId)) {
    return NextResponse.json({ detail: '잘못된 clip id' }, { status: 400 });
  }
  const stateParam = req.nextUrl.searchParams.get('state') ?? 'pending';
  if (!STATES.includes(stateParam as TriageListState)) {
    return NextResponse.json({ detail: `잘못된 state: ${stateParam}` }, { status: 400 });
  }
  const state = stateParam as TriageListState;

  const parsed = parseTriageClipFilters(req.nextUrl.searchParams);
  if ('error' in parsed) {
    return NextResponse.json({ detail: parsed.error }, { status: 400 });
  }

  try {
    const { data, error } = await supabaseAdmin
      .from('clip_labeling_triage')
      .select(DETAIL_SELECT)
      .eq('clip_id', clipId)
      .limit(1);
    if (error) throw error;
    const row = ((data ?? []) as unknown as TriageJoinRow[])[0];
    if (!row) {
      return NextResponse.json({ detail: 'triage 항목을 찾을 수 없어.' }, { status: 404 });
    }

    // URL state 와 실제 유효 상태가 다르면 stale 탭 → 잘못된 버튼을 렌더하지 않게 409(설계 §5.2).
    // client 는 실제 상태 탭으로 이동하거나 목록으로 복귀한다.
    const actualState = effectiveTriageState({
      suggested_route: row.suggested_route,
      owner_decision: row.owner_decision,
    });
    if (actualState !== state) {
      return NextResponse.json(
        { detail: '이 영상의 상태가 바뀌었어.', code: 'state_changed', state: actualState },
        { status: 409 },
      );
    }

    // 같은 탭·같은 필터에서 현재 clip 을 제외한 첫 항목 = 결정 후 이동할 다음 대상(설계 §4.2-5).
    let nextQuery = supabaseAdmin
      .from('clip_labeling_triage')
      .select('clip_id,camera_clips!inner(camera_id,started_at)')
      .neq('clip_id', clipId);
    nextQuery = applyTriageStateFilter(nextQuery, state);
    nextQuery = applyTriageClipFilters(nextQuery, parsed.filters);
    const { data: nextData, error: nextErr } = await nextQuery
      .order('updated_at', { ascending: false })
      .order('clip_id', { ascending: false })
      .limit(1);
    if (nextErr) throw nextErr;
    const nextClipId = (nextData ?? [])[0]?.clip_id ?? null;

    return NextResponse.json({
      item: mapTriageRowToDetail(row),
      next_clip_id: nextClipId,
    });
  } catch (cause) {
    return databaseUnavailable('labeling triage detail', cause);
  }
}

// PATCH /api/labeling-triage/[clipId]  body = { decision, expected_updated_at, note? }
// owner-only. fn_decide_clip_labeling_triage 로 원자 처리하고 도메인 코드를 그대로 매핑한다.
export async function PATCH(
  req: NextRequest,
  { params }: { params: { clipId: string } },
) {
  const owner = await requireOwner(req);
  if (!owner.ok) return owner.response;

  const clipId = params.clipId;
  if (!UUID_RE.test(clipId)) {
    return NextResponse.json({ detail: '잘못된 clip id' }, { status: 400 });
  }

  let body: { decision?: unknown; expected_updated_at?: unknown; note?: unknown };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ detail: '요청 형식이 잘못됐어.' }, { status: 400 });
  }

  const decision = body?.decision;
  if (typeof decision !== 'string' || !DECISIONS.includes(decision as Decision)) {
    return NextResponse.json({ detail: `잘못된 decision: ${String(decision)}` }, { status: 400 });
  }
  const expected = body?.expected_updated_at;
  if (typeof expected !== 'string' || Number.isNaN(Date.parse(expected))) {
    return NextResponse.json({ detail: 'expected_updated_at 이 잘못됐어.' }, { status: 400 });
  }
  const note = body?.note;
  if (note !== undefined && note !== null && (typeof note !== 'string' || note.length > 500)) {
    return NextResponse.json({ detail: '메모가 너무 길어.' }, { status: 400 });
  }

  const { data, error } = await supabaseAdmin.rpc('fn_decide_clip_labeling_triage', {
    p_clip_id: clipId,
    p_decided_by: owner.userId,
    p_decision: decision,
    p_expected_updated_at: expected,
    p_note: (note as string | undefined) ?? null,
  });
  if (error) {
    // 잘못된 인자(enum/길이)만 400, 그 외는 일반화된 502. DB 메시지·테이블명 비노출.
    if (error.code === '22023') {
      return NextResponse.json({ detail: '요청을 처리할 수 없어.' }, { status: 400 });
    }
    return databaseUnavailable('labeling triage decide', error);
  }

  return mapDecisionResult(data);
}

// RPC jsonb 결과 → HTTP. 도메인 코드(not_found/stale_state/labeling_started)를 정확히 매핑.
function mapDecisionResult(data: unknown): NextResponse {
  const result = data as {
    ok?: boolean;
    code?: string;
    row?: { clip_id?: string; suggested_route?: string; owner_decision?: string | null; updated_at?: string };
  } | null;

  if (!result || result.ok !== true) {
    const code = result?.code;
    if (code === 'not_found') {
      return NextResponse.json({ detail: 'triage 항목을 찾을 수 없어.' }, { status: 404 });
    }
    if (code === 'stale_state') {
      return NextResponse.json(
        { detail: '다른 화면에서 먼저 변경됐어. 새로고침해줘.', code: 'stale_state' },
        { status: 409 },
      );
    }
    if (code === 'labeling_started') {
      return NextResponse.json(
        { detail: '이미 라벨링이 시작되어 격리할 수 없어.', code: 'labeling_started' },
        { status: 409 },
      );
    }
    return NextResponse.json({ detail: '요청을 처리할 수 없어.' }, { status: 400 });
  }

  // 성공 — raw row(evidence 포함) 를 그대로 반환하지 않고 안전 필드만 추린다.
  const row = result.row ?? {};
  return NextResponse.json({
    ok: true,
    clip_id: row.clip_id ?? null,
    effective_state: effectiveTriageState(
      row.suggested_route
        ? {
            suggested_route: row.suggested_route as 'label' | 'quarantine',
            owner_decision: (row.owner_decision as 'label' | 'skip' | null) ?? null,
          }
        : null,
    ),
    updated_at: row.updated_at ?? null,
  });
}
