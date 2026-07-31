import { NextRequest, NextResponse } from 'next/server';

import { databaseUnavailable } from '@/lib/apiErrors';
import { requireLabelingAccess } from '@/lib/labelingAccess';
import { mapBoundaryWorkspace } from '@/lib/rbaBoundaryServer';
import { supabaseAdmin } from '@/lib/supabase';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(req: NextRequest) {
  // 탈퇴 peer에게 assignment가 남아도 여기서 먼저 차단한다(설계 §3).
  const access = await requireLabelingAccess(req);
  if (!access.ok) return access.response;
  try {
    const { data, error } = await supabaseAdmin.rpc('fn_get_rba_boundary_workspace', {
      p_reviewer_id: access.userId,
    });
    if (error) return databaseUnavailable('rba boundary workspace', error);
    return NextResponse.json({ workspace: mapBoundaryWorkspace(data) });
  } catch (cause) {
    return databaseUnavailable('rba boundary workspace', cause);
  }
}
