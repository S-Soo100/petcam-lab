import { NextRequest, NextResponse } from 'next/server';
import { randomUUID } from 'node:crypto';
import { presignPut } from '@/lib/r2';
import { SPECIES } from '@/types';

// POST /api/upload/sign
// 클라이언트가 R2 에 직접 PUT 하기 전에 서명된 URL + r2_key 발급.
//
// 왜 메타 검증 여기서?
// - finalize 단계에서도 검증하지만, 잘못된 species/duration 으로 R2 에 올린 뒤
//   finalize 가 거절하면 orphan object 가 남음. sign 단계에서 미리 막는다.
// - file size 는 클라이언트가 거짓말할 수 있어 hard-cap 으로만 쓰고, 실 검증은
//   R2 가 PUT 받을 때 ContentLength 로 처리. (50MB 넘는 파일은 R2 가 success
//   하더라도 finalize 에서 메타 부정합으로 잡히지만, 1차에선 sign 단계 검증 생략.)
//
// 응답: { r2_key, put_url, expires_in_sec }

export const runtime = 'nodejs'; // S3 SDK 는 edge 에서 잘 안 돎

const MAX_BYTES = 50 * 1024 * 1024;

interface SignBody {
  filename?: string;
  size?: number;
  species?: string;
  duration_sec?: number;
}

function todayDir(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

export async function POST(req: NextRequest) {
  let body: SignBody;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: 'JSON body 필요' }, { status: 400 });
  }

  const { filename, size, species, duration_sec } = body;

  if (typeof species !== 'string' || !(SPECIES as readonly string[]).includes(species)) {
    return NextResponse.json({ error: `잘못된 종: ${species}` }, { status: 400 });
  }
  if (typeof duration_sec !== 'number' || !Number.isFinite(duration_sec) || duration_sec <= 0) {
    return NextResponse.json({ error: 'duration_sec 누락/잘못' }, { status: 400 });
  }
  if (typeof size !== 'number' || size <= 0 || size > MAX_BYTES) {
    return NextResponse.json(
      { error: `파일 크기 ${size}B (1B~${MAX_BYTES}B 허용)` },
      { status: 413 },
    );
  }

  // r2_key — backend pattern 과 통일: clips/<source>/<date>/<uuid>.mp4
  // backend 는 `clips/<camera_id>/<date>/<stem>_<clip_id>.mp4` 인데, 업로드는
  // camera_id 가 없으니 source='upload' 로 prefix 분리. backend 가 나중에 list
  // 할 때 prefix 로 두 stream 구분 가능.
  const uuid = randomUUID();
  const key = `clips/upload/${todayDir()}/${uuid}.mp4`;

  let putUrl: string;
  try {
    putUrl = await presignPut(key, 'video/mp4');
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    return NextResponse.json({ error: `presign 실패: ${msg}` }, { status: 500 });
  }

  return NextResponse.json(
    {
      r2_key: key,
      put_url: putUrl,
      expires_in_sec: 300,
      filename: filename ?? null,
    },
    { status: 200 },
  );
}
