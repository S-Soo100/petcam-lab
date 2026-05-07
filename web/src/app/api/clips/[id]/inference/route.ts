import { NextRequest, NextResponse } from 'next/server';
import { supabaseAdmin } from '@/lib/supabase';
import { loadClipWithPerms } from '@/lib/clipPerms';

// GET /api/clips/[id]/inference
// behavior_logs source=vlm 최신 1건 — owner-only.
// backend/routers/labels.py `get_clip_inference` 와 동치.
//
// 추론이 없으면 null (404 아님 — UI 가 "VLM 추론 없음"으로 표시).

export const runtime = 'nodejs';

export async function GET(
  req: NextRequest,
  { params }: { params: { id: string } },
) {
  const result = await loadClipWithPerms(req, params.id);
  if (!result.ok) return result.response;
  const { isOwner } = result.access;

  if (!isOwner) {
    return NextResponse.json(
      { detail: 'only clip owner can view VLM inference' },
      { status: 403 },
    );
  }

  const { data, error } = await supabaseAdmin
    .from('behavior_logs')
    .select('*')
    .eq('clip_id', params.id)
    .eq('source', 'vlm')
    .order('created_at', { ascending: false })
    .limit(1);

  if (error) {
    return NextResponse.json(
      { detail: `supabase error: ${error.message}` },
      { status: 502 },
    );
  }
  const row = (data ?? [])[0] ?? null;
  return NextResponse.json(row);
}
