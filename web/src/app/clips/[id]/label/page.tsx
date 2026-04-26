import { notFound } from 'next/navigation';
import { supabaseAdmin } from '@/lib/supabase';
import LabelForm from './LabelForm';

export const dynamic = 'force-dynamic';

export default async function LabelPage({ params }: { params: { id: string } }) {
  const { data, error } = await supabaseAdmin
    .from('camera_clips')
    .select('id, started_at, duration_sec, source, has_motion, pet_id, camera_id')
    .eq('id', params.id)
    .single();
  if (error || !data) notFound();

  // 기존 GT 라벨 있으면 표시 (재라벨링 시)
  const { data: existing } = await supabaseAdmin
    .from('behavior_logs')
    .select('action, notes, created_at')
    .eq('clip_id', params.id)
    .eq('source', 'human')
    .order('created_at', { ascending: false })
    .limit(1);

  return <LabelForm clip={data} existing={existing?.[0] ?? null} />;
}
