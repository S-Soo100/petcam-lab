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
