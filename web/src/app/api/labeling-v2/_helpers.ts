import { NextResponse } from 'next/server';

import { supabaseAdmin } from '@/lib/supabase';
import type { LabelingSession } from '@/lib/labelingV2';

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

export function databaseError(error: unknown) {
  return NextResponse.json(
    { detail: `supabase error: ${(error as Error).message}` },
    { status: 502 },
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
