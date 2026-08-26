import { NextRequest, NextResponse } from 'next/server';

import { databaseUnavailable } from '@/lib/apiErrors';
import { requireOwner } from '@/lib/labelingAccess';
import { computeNightCoverage, parseRapRecordingQuery, toPublicRecording } from '@/lib/rapRecordings';
import { supabaseAdmin } from '@/lib/supabase';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const PUBLIC_SELECT =
  'id,mode,camera_key,test_run_id,night_date,scheduled_start_utc,actual_start_utc,partial,' +
  'duration_sec,codec,width,height,fps,video_size_bytes,capture_status,upload_status,last_error_code,uploaded_at';

export async function GET(req: NextRequest) {
  const owner = await requireOwner(req);
  if (!owner.ok) return owner.response;

  let filters;
  try {
    filters = parseRapRecordingQuery(req.nextUrl.searchParams);
  } catch {
    return NextResponse.json({ detail: '잘못된 조회 조건' }, { status: 400 });
  }

  try {
    let query = supabaseAdmin.from('rap_c500g_recordings').select(PUBLIC_SELECT).eq('mode', filters.mode);
    if (filters.camera) query = query.eq('camera_key', filters.camera);
    if (filters.night) query = query.eq('night_date', filters.night);
    if (filters.status) query = query.eq('upload_status', filters.status);
    const { data, error } = await query.order('scheduled_start_utc', { ascending: false }).limit(filters.limit);
    if (error) throw error;
    const items = (data ?? []).map((row) => toPublicRecording(row as unknown as Record<string, unknown>));
    return NextResponse.json({
      items,
      coverage: filters.mode === 'production' ? computeNightCoverage(items, filters.camera ? 1 : 3) : null,
    });
  } catch (cause) {
    return databaseUnavailable('RAP recording list', cause);
  }
}
