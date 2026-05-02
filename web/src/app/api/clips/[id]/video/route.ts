import { NextRequest } from 'next/server';
import fs from 'node:fs/promises';
import path from 'node:path';
import { supabaseAdmin } from '@/lib/supabase';

// 영상 stream. PoC는 전체 buffer로 응답 (60초 mp4 ~10MB OK).
// HTML5 video element는 progressive 재생 가능. seek은 전체 다운로드 후 동작.
// 라운드 2~ 큰 영상은 Range 응답으로 격상.
export async function GET(_req: NextRequest, { params }: { params: { id: string } }) {
  const { data, error } = await supabaseAdmin
    .from('camera_clips')
    .select('file_path')
    .eq('id', params.id)
    .single();
  if (error || !data) return new Response('not found', { status: 404 });

  const fp = data.file_path as string;
  // path traversal sanity. PoC라 service-role 키로 가져온 값이지만 방어층 1.
  if (!path.isAbsolute(fp) || fp.includes('..')) {
    return new Response('forbidden path', { status: 403 });
  }

  const buf = await fs.readFile(fp).catch(() => null);
  if (!buf) return new Response('file missing on disk', { status: 410 });

  return new Response(new Uint8Array(buf), {
    headers: {
      'Content-Type': 'video/mp4',
      'Content-Length': String(buf.length),
      'Accept-Ranges': 'bytes',
      'Cache-Control': 'private, max-age=300',
    },
  });
}
