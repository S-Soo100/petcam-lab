import { NextRequest, NextResponse } from 'next/server';

import { databaseUnavailable } from '@/lib/apiErrors';
import { requireOwner } from '@/lib/labelingAccess';
import { presignGet, SIGNED_URL_TTL_SEC } from '@/lib/r2';
import { supabaseAdmin } from '@/lib/supabase';
import { mapSignedYoloOwnerOverview } from '@/lib/yoloContributionServer';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(req: NextRequest) {
  const access = await requireOwner(req);
  if (!access.ok) return access.response;
  try {
    const { data, error } = await supabaseAdmin.rpc('fn_get_yolo_owner_overview', { p_owner_id: access.userId });
    if (error) return databaseUnavailable('yolo owner overview', error);
    return NextResponse.json(await mapSignedYoloOwnerOverview(
      data,
      (ref) => presignGet(ref, SIGNED_URL_TTL_SEC),
    ));
  } catch (cause) {
    return databaseUnavailable('yolo owner overview', cause);
  }
}
