import Link from 'next/link';
import { supabaseAdmin } from '@/lib/supabase';

export const dynamic = 'force-dynamic'; // 큐는 항상 최신 — 페이지 캐시 무효화

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
  // 1. 이미 GT 라벨된 clip_id (source='human')
  const { data: labeled } = await supabaseAdmin
    .from('behavior_logs')
    .select('clip_id')
    .eq('source', 'human');
  const labeledIds = new Set((labeled ?? []).map((r) => r.clip_id as string));

  // 2. 라운드 1 풀: cam2 motion + 업로드 — DEV_USER_ID 한정 (mirror 복제 제외)
  const { data: clips, error } = await supabaseAdmin
    .from('camera_clips')
    .select('id, started_at, duration_sec, source, has_motion')
    .eq('user_id', DEV_USER_ID)
    .or(`source.eq.upload,camera_id.eq.${ROUND1_CAMERA_ID}`)
    .eq('has_motion', true)
    .order('started_at', { ascending: true })
    .limit(500);

  if (error) {
    return <main className="p-8 text-red-600">DB 오류: {error.message}</main>;
  }

  const pending = (clips ?? []).filter((c) => !labeledIds.has(c.id)) as QueueClip[];
  const labeledCount = (clips ?? []).length - pending.length;

  return (
    <main className="mx-auto max-w-3xl p-8 space-y-4">
      <div className="flex items-baseline justify-between">
        <h1 className="text-2xl font-bold">F2 — 라벨 큐</h1>
        <Link href="/upload" className="text-sm text-blue-600 hover:underline">
          + 업로드
        </Link>
      </div>
      <p className="text-sm text-gray-600">
        대기 {pending.length}건 · 완료 {labeledCount}건 (라운드 1 풀: cam2 motion + 업로드)
      </p>

      {pending.length === 0 ? (
        <p className="text-gray-500">대기 중인 클립 없음. 모두 라벨 완료 또는 업로드 필요.</p>
      ) : (
        <ul className="divide-y border rounded">
          {pending.map((c) => (
            <li key={c.id}>
              <Link
                href={`/clips/${c.id}/label`}
                className="flex justify-between p-3 hover:bg-gray-50"
              >
                <span className="font-mono text-xs">{c.id.slice(0, 8)}</span>
                <span className="text-sm">{new Date(c.started_at).toLocaleString('ko-KR')}</span>
                <span className="text-sm text-gray-500">
                  {c.source} · {c.duration_sec.toFixed(1)}s
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
