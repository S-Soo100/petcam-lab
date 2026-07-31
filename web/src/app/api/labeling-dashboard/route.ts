import { NextRequest, NextResponse } from 'next/server';

import { databaseUnavailable } from '@/lib/apiErrors';
import { requireLabelingAccess } from '@/lib/labelingAccess';
import { mapLabelingDashboard } from '@/lib/rbaBoundaryServer';
import { supabaseAdmin } from '@/lib/supabase';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(req: NextRequest) {
  const access = await requireLabelingAccess(req);
  if (!access.ok) return access.response;
  const ownerId = process.env.DEV_USER_ID;
  if (!ownerId) {
    return NextResponse.json(
      { detail: '데이터 현황 설정을 확인할 수 없어.' },
      { status: 503 },
    );
  }
  try {
    const { data, error } = await supabaseAdmin.rpc('fn_get_labeling_data_dashboard', {
      p_owner_id: ownerId,
    });
    if (error) return databaseUnavailable('labeling dashboard', error);
    return NextResponse.json(mapLabelingDashboard(data));
  } catch (cause) {
    return databaseUnavailable('labeling dashboard', cause);
  }
}
