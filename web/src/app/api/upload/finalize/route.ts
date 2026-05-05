import { NextRequest, NextResponse } from 'next/server';
import { revalidatePath } from 'next/cache';
import { supabaseAdmin } from '@/lib/supabase';
import { SPECIES } from '@/types';

// POST /api/upload/finalize
// 브라우저가 R2 PUT 성공한 뒤 호출. camera_clips INSERT (r2_key 포함) +
// queue 페이지 캐시 무효화.
//
// 왜 r2_key 가 sign 응답값과 다른지 검증 안 하나?
// - 브라우저가 거짓말할 수는 있지만 실 키는 우리가 발급한 prefix(clips/upload/)
//   안이라야 의미. 추가 검증 원하면 prefix 패턴 매치만 하면 충분. 1차에선 단순화.
// - 더 강한 방어가 필요하면 sign 응답에 HMAC 서명을 박아서 finalize 가 검증.
//
// has_motion=true — 업로드는 "모션 있음" 가정 (큐에 무조건 노출).
// camera_id=null, source='upload' — 카메라 인입과 구분.

export const runtime = 'nodejs';

interface FinalizeBody {
  r2_key?: string;
  species?: string;
  duration_sec?: number;
  file_size?: number;
  filename?: string;
}

export async function POST(req: NextRequest) {
  const DEV_USER_ID = process.env.DEV_USER_ID;
  const DEV_PET_ID = process.env.DEV_PET_ID || null;
  if (!DEV_USER_ID) {
    return NextResponse.json({ error: 'DEV_USER_ID 누락' }, { status: 500 });
  }

  let body: FinalizeBody;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: 'JSON body 필요' }, { status: 400 });
  }

  const { r2_key, species, duration_sec, file_size } = body;

  if (typeof r2_key !== 'string' || !r2_key.startsWith('clips/upload/')) {
    return NextResponse.json({ error: 'r2_key 누락/포맷오류' }, { status: 400 });
  }
  if (typeof species !== 'string' || !(SPECIES as readonly string[]).includes(species)) {
    return NextResponse.json({ error: `잘못된 종: ${species}` }, { status: 400 });
  }
  if (typeof duration_sec !== 'number' || !Number.isFinite(duration_sec) || duration_sec <= 0) {
    return NextResponse.json({ error: 'duration_sec 누락/잘못' }, { status: 400 });
  }
  if (typeof file_size !== 'number' || !Number.isFinite(file_size) || file_size <= 0) {
    return NextResponse.json({ error: 'file_size 누락/잘못' }, { status: 400 });
  }

  const startedAt = new Date().toISOString();
  const { data, error } = await supabaseAdmin
    .from('camera_clips')
    .insert({
      user_id: DEV_USER_ID,
      pet_id: DEV_PET_ID,
      camera_id: null,
      source: 'upload',
      started_at: startedAt,
      duration_sec: duration_sec,
      // file_path 는 로컬 파일 없으니 NULL 이 정확하지만, DB NOT NULL 제약 가능성
      // 방어 차원에서 r2_key 를 그대로 박음. 어차피 read 측은 r2_key 우선.
      file_path: r2_key,
      file_size: file_size,
      has_motion: true,
      r2_key: r2_key,
      thumbnail_r2_key: null, // 1차에선 thumbnail skip
      // species 는 별도 컬럼 없으면 INSERT 에서 빠지지만, 백엔드 backfill 가능
    })
    .select('id')
    .single();

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  revalidatePath('/');
  revalidatePath('/queue');
  revalidatePath('/labeling');
  return NextResponse.json({ id: data.id, r2_key }, { status: 201 });
}
