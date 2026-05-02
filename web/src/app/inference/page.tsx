import Link from 'next/link';
import { supabaseAdmin } from '@/lib/supabase';
import InferenceForm from './InferenceForm';
import { Page, PageHeader } from '@/components/ui/Page';
import { Card } from '@/components/ui/Card';

export const dynamic = 'force-dynamic';

const DEV_USER_ID = process.env.DEV_USER_ID!;

export default async function InferencePage() {
  const { data: gtRows } = await supabaseAdmin
    .from('behavior_logs')
    .select('clip_id')
    .eq('source', 'human');
  const gtIds = Array.from(new Set((gtRows ?? []).map((r) => r.clip_id as string)));

  const { data: vlmRows } = await supabaseAdmin
    .from('behavior_logs')
    .select('clip_id')
    .eq('source', 'vlm');
  const vlmIds = new Set((vlmRows ?? []).map((r) => r.clip_id as string));

  const candidateIds = gtIds.filter((id) => !vlmIds.has(id));
  if (candidateIds.length === 0) {
    return (
      <Page max="3xl">
        <PageHeader title="F3 — Gemini 추론" subtitle="추론 대기 클립 없음" />
        <Card padding="lg" className="text-sm text-zinc-600">
          GT 라벨된 클립은 모두 추론 완료 상태.{' '}
          <Link href="/queue" className="text-zinc-900 underline">/queue</Link>
          에서 새 라벨 추가하거나{' '}
          <Link href="/results" className="text-zinc-900 underline">/results</Link>
          에서 평가 확인.
        </Card>
      </Page>
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
