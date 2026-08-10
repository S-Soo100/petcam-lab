import { NextRequest, NextResponse } from 'next/server';

import { databaseUnavailable } from '@/lib/apiErrors';
import { requireLabelingAccess } from '@/lib/labelingAccess';
import { presignGet, SIGNED_URL_TTL_SEC } from '@/lib/r2';
import { supabaseAdmin } from '@/lib/supabase';
import { mapSignedBlindWorkspace } from '@/lib/yoloContributionServer';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(req: NextRequest) {
  const access = await requireLabelingAccess(req);
  if (!access.ok) return access.response;
  try {
    const { data, error } = await supabaseAdmin.rpc('fn_get_yolo_bbox_workspace', {
      p_contributor_id: access.userId,
    });
    if (error) return databaseUnavailable('yolo contribution workspace', error);
    const workspace = await mapSignedBlindWorkspace(
      data,
      (ref) => presignGet(ref, SIGNED_URL_TTL_SEC),
    );
    return NextResponse.json({ workspace });
  } catch (cause) {
    return databaseUnavailable('yolo contribution workspace', cause);
  }
}
