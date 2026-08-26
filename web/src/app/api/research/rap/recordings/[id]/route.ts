import { NextRequest, NextResponse } from 'next/server';

import { databaseUnavailable } from '@/lib/apiErrors';
import { requireOwner } from '@/lib/labelingAccess';
import { presignGet } from '@/lib/r2';
import { toPublicRecording } from '@/lib/rapRecordings';
import { supabaseAdmin } from '@/lib/supabase';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const DETAIL_SELECT =
  'id,mode,camera_key,test_run_id,night_date,scheduled_start_utc,actual_start_utc,partial,' +
  'duration_sec,codec,width,height,fps,video_size_bytes,capture_status,upload_status,last_error_code,uploaded_at,' +
  'video_r2_key,thumbnail_r2_key';

export async function GET(req: NextRequest, { params }: { params: { id: string } }) {
  const owner = await requireOwner(req);
  if (!owner.ok) return owner.response;
  if (!UUID_RE.test(params.id)) return NextResponse.json({ detail: '잘못된 id' }, { status: 400 });

  try {
    const { data, error } = await supabaseAdmin
      .from('rap_c500g_recordings')
      .select(DETAIL_SELECT)
      .eq('id', params.id)
      .single();
    if (error || !data) {
      if ((error as { code?: string } | null)?.code === 'PGRST116' || !data) {
        return NextResponse.json({ detail: 'recording not found' }, { status: 404 });
      }
      throw error;
    }
    const row = data as unknown as Record<string, unknown>;
    if (row.upload_status !== 'uploaded' || !row.video_r2_key || !row.thumbnail_r2_key) {
      return NextResponse.json({ detail: 'recording media unavailable' }, { status: 409 });
    }
    const [videoUrl, thumbnailUrl] = await Promise.all([
      presignGet(String(row.video_r2_key), 3600),
      presignGet(String(row.thumbnail_r2_key), 3600),
    ]);
    return NextResponse.json({
      recording: toPublicRecording(row),
      video_url: videoUrl,
      thumbnail_url: thumbnailUrl,
      expires_in: 3600,
    });
  } catch (cause) {
    return databaseUnavailable('RAP recording detail', cause);
  }
}
