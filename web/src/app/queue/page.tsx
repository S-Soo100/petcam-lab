import Link from 'next/link';
import { supabaseAdmin } from '@/lib/supabase';
import { Page, PageHeader } from '@/components/ui/Page';
import { Card } from '@/components/ui/Card';
import Badge from '@/components/ui/Badge';

export const dynamic = 'force-dynamic';

const DEV_USER_ID = process.env.DEV_USER_ID!;
const ROUND1_CAMERA_ID = process.env.ROUND1_CAMERA_ID!;

interface QueueClip {
  id: string;
  started_at: string;
  duration_sec: number;
  source: 'camera' | 'upload' | 'youtube';
  has_motion: boolean;
}

export default async function QueuePage() {
  const { data: labeled } = await supabaseAdmin
    .from('behavior_logs')
    .select('clip_id')
    .eq('source', 'human');
  const labeledIds = new Set((labeled ?? []).map((r) => r.clip_id as string));

  const { data: clips, error } = await supabaseAdmin
    .from('camera_clips')
    .select('id, started_at, duration_sec, source, has_motion')
    .eq('user_id', DEV_USER_ID)
    .or(`source.eq.upload,camera_id.eq.${ROUND1_CAMERA_ID}`)
    .eq('has_motion', true)
    .order('started_at', { ascending: true })
    .limit(500);

  if (error) {
    return (
      <Page max="3xl">
        <Card className="border-red-200 bg-red-50 text-red-700">DB 오류: {error.message}</Card>
      </Page>
    );
  }

  const pending = (clips ?? []).filter((c) => !labeledIds.has(c.id)) as QueueClip[];
  const labeledCount = (clips ?? []).length - pending.length;

  return (
    <Page max="3xl">
      <PageHeader
        title="F2 — GT 라벨링 큐"
        subtitle={`대기 ${pending.length}건 · 완료 ${labeledCount}건`}
        right={
          <Link
            href="/upload"
            className="rounded-md border border-zinc-300 bg-white px-3 py-1.5 text-sm font-medium text-zinc-700 hover:bg-zinc-50"
          >
            + 업로드
          </Link>
        }
      />

      {pending.length === 0 ? (
        <Card className="text-center text-sm text-zinc-500" padding="lg">
          대기 중인 클립 없음. 모두 라벨 완료 또는 업로드 필요.
        </Card>
      ) : (
        <Card padding="none">
          <ul className="divide-y divide-zinc-100">
            {pending.map((c, i) => (
              <li key={c.id}>
                <Link
                  href={`/clips/${c.id}/label`}
                  className="flex items-center gap-4 px-4 py-3 transition-colors hover:bg-zinc-50"
                >
                  <span className="w-6 text-right text-xs tabular-nums text-zinc-400">
                    {i + 1}
                  </span>
                  <span className="font-mono text-xs text-zinc-500">{c.id.slice(0, 8)}</span>
                  <span className="flex-1 text-sm text-zinc-700">
                    {new Date(c.started_at).toLocaleString('ko-KR', {
                      timeZone: 'Asia/Seoul',
                      dateStyle: 'short',
                      timeStyle: 'short',
                    })}
                  </span>
                  <Badge tone={c.source === 'upload' ? 'info' : 'neutral'}>{c.source}</Badge>
                  <span className="w-12 text-right text-xs tabular-nums text-zinc-500">
                    {c.duration_sec.toFixed(0)}s
                  </span>
                  <span className="text-zinc-300">→</span>
                </Link>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </Page>
  );
}
