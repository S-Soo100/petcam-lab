import { NextRequest, NextResponse } from 'next/server';
import { supabaseAdmin } from '@/lib/supabase';
import { loadClipWithPerms } from '@/lib/clipPerms';

// GET /api/clips/[id]/labels
// behavior_labels 목록 — owner 전체 / labeler 본인만 / 외부인 404.
// backend/routers/labels.py `list_labels` 와 동치.

export const runtime = 'nodejs';

export async function GET(
  req: NextRequest,
  { params }: { params: { id: string } },
) {
  const result = await loadClipWithPerms(req, params.id);
  if (!result.ok) return result.response;
  const { userId, isOwner } = result.access;

  let q = supabaseAdmin
    .from('behavior_labels')
    .select('*')
    .eq('clip_id', params.id)
    .order('labeled_at', { ascending: false });

  if (!isOwner) {
    // labeler 는 본인 라벨만 (다른 라벨러 결과 비공개 — 영향 회피).
    q = q.eq('labeled_by', userId);
  }

  const { data, error } = await q;
  if (error) {
    return NextResponse.json(
      { detail: `supabase error: ${error.message}` },
      { status: 502 },
    );
  }
  return NextResponse.json(data ?? []);
}
