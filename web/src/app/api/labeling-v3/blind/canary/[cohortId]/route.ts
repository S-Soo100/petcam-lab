import { NextRequest, NextResponse } from 'next/server';

import { supabaseAdmin } from '@/lib/supabase';
import { requireProductionLabelingAccess } from '@/lib/labelingAccess';
import {
  blindBadRequest,
  blindDatabaseError,
  blindRpcErrorResponse,
  isValidUuid,
  mapBlindQueueRow,
  type BlindQueueRow,
} from '@/lib/motionBlindReviewServer';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

// GET /api/labeling-v3/blind/canary/[cohortId] — 동일 링크, 역할별 렌더(설계 §8).
//
// 라벨러: 자기에게 배정된 canary 영상 + 본인 제출 수/전체 수. 상대 답안·상대 제출 상태 비공개.
// Owner:  cohort 이름·상태·전체 영상 수 + 두 라벨러 이름/각 완료 수 + 상태 집계 + 공유 링크.
//         한 사람만 제출한 개별 답안은 표시하지 않는다 — motion_clip_blind_submissions 를 select 하지 않는다.
// Owner 도 라벨러도 아닌 사용자는 requireProductionLabelingAccess 가 403 으로 막는다.
export async function GET(req: NextRequest, { params }: { params: { cohortId: string } }) {
  const access = await requireProductionLabelingAccess(req);
  if (!access.ok) return access.response;

  if (!isValidUuid(params.cohortId)) return blindBadRequest('잘못된 cohort id');
  const cohortId = params.cohortId;

  try {
    const { data: cohortData, error: cohortErr } = await supabaseAdmin
      .from('motion_blind_review_cohorts')
      .select('id, status, kind, label, group_id')
      .eq('id', cohortId)
      .limit(1);
    if (cohortErr) throw cohortErr;
    const cohort = (cohortData ?? [])[0] as
      | { status?: string; kind?: string; label?: string | null; group_id?: string | null }
      | undefined;
    // 미존재/비-canary 는 존재를 드러내지 않는 만료 상태로 접는다(양 역할 공통).
    if (!cohort || cohort.kind !== 'canary') {
      return NextResponse.json(
        { detail: '검증 링크가 만료됐어.', code: 'cohort_closed' },
        { status: 410 },
      );
    }

    if (access.isOwner) {
      return await ownerDashboard(cohortId, cohort);
    }

    // 라벨러: 닫힌 cohort 는 만료(설계 §8·§11). 개별 답안은 애초에 노출하지 않는다.
    if (cohort.status !== 'open') {
      return NextResponse.json(
        { detail: '검증 링크가 만료됐어.', code: 'cohort_closed' },
        { status: 410 },
      );
    }
    return await labelerQueue(cohortId, access.userId);
  } catch (cause) {
    return blindDatabaseError(cause);
  }
}

// 라벨러 branch — 자기 canary slot 미제출분 + 본인 진행 집계. 상대 판정은 세지 않는다.
async function labelerQueue(cohortId: string, userId: string): Promise<NextResponse> {
  const { data, error } = await supabaseAdmin.rpc('fn_list_motion_blind_queue', {
    p_reviewer_id: userId,
    p_activity_day: null,
    p_cohort_kind: 'canary',
    p_cohort_id: cohortId,
    p_cursor_detected: null,
    p_cursor_activity_sec: null,
    p_cursor_started_at: null,
    p_cursor_id: null,
    p_limit: 100,
  });
  if (error) return blindRpcErrorResponse(error) ?? blindDatabaseError(error);
  const items = ((data ?? []) as BlindQueueRow[]).map(mapBlindQueueRow);

  const { data: slotData, error: slotErr } = await supabaseAdmin
    .from('motion_clip_review_slots')
    .select('submitted_at')
    .eq('reviewer_id', userId)
    .eq('cohort_kind', 'canary')
    .eq('cohort_id', cohortId);
  if (slotErr) throw slotErr;
  const slots = (slotData ?? []) as { submitted_at: string | null }[];

  return NextResponse.json({
    role: 'labeler',
    cohort_id: cohortId,
    items,
    total_count: slots.length,
    submitted_count: slots.filter((s) => s.submitted_at != null).length,
  });
}

// Owner branch — cohort 현황판. 두 라벨러 이름/완료 수 + 상태 집계. 개별 제출 body 는 select 안 함.
async function ownerDashboard(
  cohortId: string,
  cohort: { status?: string; label?: string | null; group_id?: string | null },
): Promise<NextResponse> {
  // reviewer 정본 = 이 cohort 의 slot snapshot(생성 당시 배정, review-fix P1-3). 현재 group member
  // 목록은 쓰지 않는다 — 그룹 멤버가 교체돼도 canary 는 원래 배정된 두 reviewer 로 채점·표시해야 한다.
  // 개별 제출 원문(initial_gt/decision)은 select 하지 않는다.
  const { data: slotData, error: slotErr } = await supabaseAdmin
    .from('motion_clip_review_slots')
    .select('reviewer_id, submitted_at, clip_id')
    .eq('cohort_id', cohortId);
  if (slotErr) throw slotErr;
  const slots = (slotData ?? []) as {
    reviewer_id: string;
    submitted_at: string | null;
    clip_id: string;
  }[];
  const submittedByReviewer = new Map<string, number>();
  const totalByReviewer = new Map<string, number>();
  const clipSet = new Set<string>();
  for (const s of slots) {
    clipSet.add(s.clip_id);
    totalByReviewer.set(s.reviewer_id, (totalByReviewer.get(s.reviewer_id) ?? 0) + 1);
    if (s.submitted_at != null) {
      submittedByReviewer.set(s.reviewer_id, (submittedByReviewer.get(s.reviewer_id) ?? 0) + 1);
    }
  }
  const reviewerIds = Array.from(totalByReviewer.keys()).sort();

  // display_name 매핑(이메일·UUID 는 응답에 담지 않는다). slot snapshot 의 reviewer 만 lookup.
  const nameMap = new Map<string, string>();
  if (reviewerIds.length > 0) {
    const { data: appData, error: appErr } = await supabaseAdmin
      .from('labeler_applications')
      .select('user_id, display_name')
      .in('user_id', reviewerIds);
    if (appErr) throw appErr;
    for (const a of (appData ?? []) as { user_id: string; display_name: string | null }[]) {
      if (a.display_name) nameMap.set(a.user_id, a.display_name);
    }
  }

  const reviewers = reviewerIds.map((id) => ({
    display_name: nameMap.get(id) ?? '라벨러',
    submitted_count: submittedByReviewer.get(id) ?? 0,
    total_count: totalByReviewer.get(id) ?? 0,
  }));

  // consensus 상태 집계(개별 답 아님).
  const { data: consData, error: consErr } = await supabaseAdmin
    .from('motion_clip_consensus')
    .select('status')
    .eq('cohort_id', cohortId);
  if (consErr) throw consErr;
  const counts = { awaiting: 0, agreed: 0, conflict: 0, owner_resolved: 0 };
  for (const c of (consData ?? []) as { status: string }[]) {
    if (c.status in counts) counts[c.status as keyof typeof counts] += 1;
  }

  return NextResponse.json({
    role: 'owner',
    cohort_id: cohortId,
    label: cohort.label ?? null,
    status: cohort.status === 'open' ? 'open' : 'closed',
    clip_total: clipSet.size,
    reviewers,
    counts,
    share_path: `/labeling/blind/canary/${cohortId}`,
  });
}
