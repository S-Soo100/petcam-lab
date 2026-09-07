import 'server-only';

import { mapBehaviorFlagRow, type BehaviorFlagRow } from '@/lib/labelingV4Server';
import type { V4BehaviorFlag } from '@/lib/labelingV4';
import { supabaseAdmin } from '@/lib/supabase';
import { resolveReviewerName } from './_access';
import { HighlightRpcError } from './_highlight';

function mapResult(data: unknown): V4BehaviorFlag {
  if (!Array.isArray(data) || data.length !== 1) throw new Error('invalid_behavior_flag_result_count');
  return mapBehaviorFlagRow(data[0] as BehaviorFlagRow, (id, name) => resolveReviewerName({ reviewerId: id, displayName: name }));
}

// "의미있는 행동" 체크 상태(RPC 전용 테이블 — 직접 select 없음).
export async function loadBehaviorFlag(clipId: string): Promise<V4BehaviorFlag> {
  const { data, error } = await supabaseAdmin.rpc('fn_get_motion_clip_behavior_flag', { p_clip_id: clipId });
  if (error) throw new HighlightRpcError(error);
  return mapResult(data);
}

// 체크/해제. 해제 권한(체크한 사람·owner)·적격 검사는 DB 함수가 한다(PT403/P0002 → route 가 매핑).
export async function setBehaviorFlag(clipId: string, userId: string, isOwner: boolean, flagged: boolean): Promise<V4BehaviorFlag> {
  const { data, error } = await supabaseAdmin.rpc('fn_set_motion_clip_behavior_flag', {
    p_clip_id: clipId, p_user_id: userId, p_is_owner: isOwner, p_flagged: flagged,
  });
  if (error) throw new HighlightRpcError(error);
  return mapResult(data);
}
