import Link from 'next/link';
import { supabaseAdmin } from '@/lib/supabase';
import InferenceForm from './InferenceForm';

export const dynamic = 'force-dynamic';

const DEV_USER_ID = process.env.DEV_USER_ID!;

export default async function InferencePage() {
  // GT 있는 클립 (source='human')
  const { data: gtRows } = await supabaseAdmin
    .from('behavior_logs')
    .select('clip_id')
    .eq('source', 'human');
  const gtIds = Array.from(new Set((gtRows ?? []).map((r) => r.clip_id as string)));

  // 이미 VLM 추론된 클립 (재추론 방지)
  const { data: vlmRows } = await supabaseAdmin
    .from('behavior_logs')
    .select('clip_id')
    .eq('source', 'vlm');
  const vlmIds = new Set((vlmRows ?? []).map((r) => r.clip_id as string));

  const candidateIds = gtIds.filter((id) => !vlmIds.has(id));
  if (candidateIds.length === 0) {
    return (
      <main className="mx-auto max-w-3xl p-8 space-y-4">
        <h1 className="text-2xl font-bold">F3 — Gemini 추론</h1>
        <p className="text-gray-600">
          추론 대기 클립 없음. <Link href="/queue" className="text-blue-600 hover:underline">/queue</Link>{' '}
          에서 GT 라벨 먼저 또는 <Link href="/results" className="text-blue-600 hover:underline">/results</Link>{' '}
          확인.
        </p>
      </main>
    );
  }

  const { data: clips } = await supabaseAdmin
    .from('camera_clips')
    .select('id, started_at, duration_sec, source, file_size')
    .in('id', candidateIds)
    .eq('user_id', DEV_USER_ID)
    .order('started_at', { ascending: true });

  return <InferenceForm clips={clips ?? []} />;
}
