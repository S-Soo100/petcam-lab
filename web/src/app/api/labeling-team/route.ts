import { NextRequest, NextResponse } from 'next/server';

import { requireOwner } from '@/lib/labelingAccess';
import { supabaseAdmin } from '@/lib/supabase';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

// GET /api/labeling-team
// owner 전용 — 신청을 상태·신청일(desc)로 반환한다. 클라이언트가 대기/활동중/거절 3구역으로 나눈다.
export async function GET(req: NextRequest) {
  const owner = await requireOwner(req);
  if (!owner.ok) return owner.response;

  const { data, error } = await supabaseAdmin
    .from('labeler_applications')
    .select('user_id, email, display_name, status, requested_at, reviewed_at')
    .order('status', { ascending: true })
    .order('requested_at', { ascending: false });
  if (error) {
    return NextResponse.json(
      { detail: `supabase error: ${error.message}` },
      { status: 502 },
    );
  }

  return NextResponse.json({ applications: data ?? [] });
}
