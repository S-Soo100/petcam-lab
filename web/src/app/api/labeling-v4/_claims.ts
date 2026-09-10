import 'server-only';

import { supabaseAdmin } from '@/lib/supabase';

// "보는 중" 힌트(UX ⑤). 잠금이 아니라 다음 영상 추천에서 남이 최근에 연 clip 을 피하는 용도.
export const VIEW_CLAIM_TTL_SEC = 120;

// 상세 열 때 호출. 실패해도 흐름을 막지 않는다(힌트).
export async function claimView(clipId: string, userId: string): Promise<void> {
  try {
    await supabaseAdmin.rpc('fn_claim_motion_clip_view', { p_clip_id: clipId, p_user_id: userId });
  } catch {
    // 힌트 저장 실패는 무시.
  }
}

// 후보 순서를 지키며 남이 TTL 안에 연 clip 을 건너뛴다. 전부 남이 보고 있거나 조회 실패면 첫 후보.
export async function pickUnclaimed(candidateIds: string[], userId: string): Promise<string | null> {
  if (candidateIds.length === 0) return null;
  try {
    const { data, error } = await supabaseAdmin.rpc('fn_fresh_motion_clip_view_claims', {
      p_clip_ids: candidateIds, p_exclude_user: userId, p_ttl_sec: VIEW_CLAIM_TTL_SEC,
    });
    if (error) throw error;
    const taken = new Set(((data ?? []) as { clip_id?: unknown }[]).map((r) => r.clip_id).filter((v): v is string => typeof v === 'string'));
    return candidateIds.find((id) => !taken.has(id)) ?? candidateIds[0];
  } catch {
    return candidateIds[0];
  }
}

// 후보를 몇 개 받아 둘지 — 동시에 같은 카메라를 보는 사람 수보다 넉넉하게.
export const NEXT_CANDIDATES = 6;
