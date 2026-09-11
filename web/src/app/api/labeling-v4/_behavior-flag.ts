import 'server-only';

import { mapBehaviorKindsRows, mapBehaviorMarks, type BehaviorMarkRow } from '@/lib/labelingV4Server';
import type { V4BehaviorFlag, V4BehaviorKind, V4BehaviorMarks, V4ClipItem } from '@/lib/labelingV4';
import { supabaseAdmin } from '@/lib/supabase';
import { resolveReviewerName } from './_access';
import { HighlightRpcError } from './_highlight';

const resolve = (id: string, name: string | null) => resolveReviewerName({ reviewerId: id, displayName: name });

function mapMarks(data: unknown): V4BehaviorMarks {
  if (!Array.isArray(data) || data.length === 0) throw new Error('invalid_behavior_marks_result');
  return mapBehaviorMarks(data as BehaviorMarkRow[], resolve);
}

// 행동 표시 4종(RPC 전용 테이블 — 직접 select 없음). 종류별 4행이 항상 온다.
export async function loadBehaviorMarks(clipId: string): Promise<V4BehaviorMarks> {
  const { data, error } = await supabaseAdmin.rpc('fn_get_motion_clip_behavior_flags', { p_clip_id: clipId });
  if (error) throw new HighlightRpcError(error);
  return mapMarks(data);
}

// 호환: 옛 단일 플래그 = meaningful.
export async function loadBehaviorFlag(clipId: string): Promise<V4BehaviorFlag> {
  return (await loadBehaviorMarks(clipId)).meaningful;
}

// 종류 하나 켜기/끄기. 해제 권한(체크한 사람·owner)·적격 검사·kind 검증은 DB 함수(PT403/P0002/22023 → route 가 매핑).
export async function setBehaviorMark(clipId: string, userId: string, isOwner: boolean, kind: V4BehaviorKind, flagged: boolean): Promise<V4BehaviorMarks> {
  const { data, error } = await supabaseAdmin.rpc('fn_set_motion_clip_behavior_flag', {
    p_clip_id: clipId, p_user_id: userId, p_is_owner: isOwner, p_kind: kind, p_flagged: flagged,
  });
  if (error) throw new HighlightRpcError(error);
  return mapMarks(data);
}

// 목록 카드 배지: 페이지 항목 id 로 배치 RPC 한 번. 보조 정보 — 실패해도 목록은 그대로(kinds []).
export async function attachBehaviorKinds(items: V4ClipItem[]): Promise<void> {
  if (items.length === 0) return;
  try {
    const { data, error } = await supabaseAdmin.rpc('fn_get_motion_clip_behavior_kinds', { p_clip_ids: items.map((i) => i.id) });
    if (error) throw error;
    const byId = mapBehaviorKindsRows((data ?? []) as { clip_id: unknown; kinds: unknown }[]);
    for (const it of items) it.behavior_kinds = byId.get(it.id) ?? [];
  } catch {
    // 보조 정보.
  }
}
