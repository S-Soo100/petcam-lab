import { NextResponse } from 'next/server';

import { supabaseAdmin } from '@/lib/supabase';
import type { LabelingSession } from '@/lib/labelingV2';
import {
  effectiveTriageState,
  type EffectiveTriageState,
} from '@/lib/labelingTriage';

export async function loadOwnSession(clipId: string, userId: string) {
  const { data, error } = await supabaseAdmin
    .from('clip_labeling_sessions')
    .select('*')
    .eq('clip_id', clipId)
    .eq('reviewed_by', userId)
    .limit(1);
  if (error) throw new Error(error.message);
  return ((data ?? [])[0] ?? null) as LabelingSession | null;
}

export async function loadLatestVlmPrediction(clipId: string) {
  const { data, error } = await supabaseAdmin
    .from('behavior_logs')
    .select('*')
    .eq('clip_id', clipId)
    .eq('source', 'vlm')
    .order('created_at', { ascending: false })
    .limit(1);
  if (error) throw new Error(error.message);
  return (data ?? [])[0] ?? null;
}

// DB 오류는 서버 로그에만 남기고 응답에는 일반화된 502 만 반환한다(설계 §7).
// Supabase 원문 메시지·테이블명·트리거 문구가 클라이언트로 새지 않게 한다.
const PUBLIC_DATABASE_ERROR = '서버 처리 중 오류가 발생했어. 잠시 후 다시 시도해.';

export function databaseError(error: unknown) {
  console.error('[labeling-v2] database error', error);
  return NextResponse.json({ detail: PUBLIC_DATABASE_ERROR }, { status: 502 });
}

// clip 의 유효 triage 상태(설계 §5.2). GT 저장 전 격리 여부 판정에 쓴다.
// triage row 없음/label/시스템 label → 'queue', 격리/스킵 → 'pending'/'skipped'.
export async function loadTriageEffectiveState(
  clipId: string,
): Promise<EffectiveTriageState> {
  const { data, error } = await supabaseAdmin
    .from('clip_labeling_triage')
    .select('suggested_route,owner_decision')
    .eq('clip_id', clipId)
    .limit(1);
  if (error) throw error;
  const row = (data ?? [])[0] ?? null;
  return effectiveTriageState(
    row as {
      suggested_route: 'label' | 'quarantine';
      owner_decision: 'label' | 'skip' | null;
    } | null,
  );
}

// behavior_labels.lick_target 파생 — GT 저장(gt route)과 owner 보정(revise route)이 공유한다.
// drinking/eating_paste 만 접촉 대상이 있고 나머지는 null.
export function mapLickTarget(action: string, target: string): string | null {
  if (action !== 'drinking' && action !== 'eating_paste') return null;
  if (target === 'water_bowl' || target === 'food_bowl') return 'dish';
  if (target === 'floor') return 'floor';
  if (target === 'glass') return 'wall';
  if (target === 'object') return 'object';
  return 'other';
}
