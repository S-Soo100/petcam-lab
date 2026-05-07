import { NextRequest, NextResponse } from 'next/server';
import { presignGet, SIGNED_URL_TTL_SEC } from '@/lib/r2';
import { loadClipWithPerms } from '@/lib/clipPerms';

// GET /api/clips/[id]/file/url
// 클립 영상 R2 signed URL 발급 — owner OR labeler.
// backend/routers/clips.py `get_clip_file_url` 와 동치.
//
// 왜 URL 만 JSON 으로 반환 (스트리밍 X):
// - <video src> 는 cross-origin 요청에 Authorization 헤더 못 넣음.
// - signed URL 은 단발 토큰 (1h TTL) → URL 만 알면 재생 가능 → auth header 불필요.
// - R2 가 직접 서빙 → Vercel 함수 비용 ↓, Range/seek 도 R2 가 처리.

export const runtime = 'nodejs';

export async function GET(
  req: NextRequest,
  { params }: { params: { id: string } },
) {
  const result = await loadClipWithPerms(req, params.id);
  if (!result.ok) return result.response;
  const { clip } = result.access;

  const r2Key = clip.r2_key;
  if (!r2Key) {
    // 로컬 fallback (file_path) 은 web prod 에선 의미 없음 — 410.
    return NextResponse.json(
      { detail: 'clip has no R2 object (local-only or pre-R2 era)' },
      { status: 410 },
    );
  }

  const url = await presignGet(r2Key, SIGNED_URL_TTL_SEC);
  return NextResponse.json({
    url,
    ttl_sec: SIGNED_URL_TTL_SEC,
    type: 'r2',
  });
}
