import { NextRequest, NextResponse } from 'next/server';

import { databaseUnavailable } from '@/lib/apiErrors';
import { requireOwner } from '@/lib/labelingAccess';
import { mapBoundaryConflicts } from '@/lib/rbaBoundaryServer';
import { supabaseAdmin } from '@/lib/supabase';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(req: NextRequest) {
  const access = await requireOwner(req);
  if (!access.ok) return access.response;
  try {
    const { data, error } = await supabaseAdmin.rpc('fn_list_rba_boundary_conflicts', {
      p_owner_id: access.userId,
    });
    if (error) return databaseUnavailable('rba boundary conflicts', error);
    return NextResponse.json(mapBoundaryConflicts(data));
  } catch (cause) {
    return databaseUnavailable('rba boundary conflicts', cause);
  }
}
