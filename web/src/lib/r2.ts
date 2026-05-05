import 'server-only';

// Cloudflare R2 (S3-compatible) 클라이언트 — 웹 라우트(/api/upload/*) 전용.
//
// 왜 boto3 가 아니라 @aws-sdk/client-s3 인가:
// - Next.js (Node) 라우트에서 Python 못 쓰니까. backend/r2_uploader.py 와 동일한
//   환경변수 컨벤션(R2_ENDPOINT/ACCESS_KEY/SECRET/BUCKET)을 그대로 따라간다.
// - boto3 비유: `Config(signature_version='s3v4', s3={'addressing_style':'path'})`
//   ≈ `forcePathStyle: true`. R2 wildcard cert(`*.r2.cloudflarestorage.com`)는 한
//   단계만 매치하므로 virtual-hosted style 쓰면 SSL handshake 실패.
//
// 왜 presigned PUT URL 패턴인가:
// - Vercel serverless body limit 4.5MB. mp4 50MB는 라우트로 못 받음.
// - 브라우저가 R2에 직접 PUT → 서버는 URL 발급 + 메타만 INSERT.
// - 비용: R2 outbound 무료, Vercel 함수 실행시간 단축.
//
// 싱글톤 lazy 초기화 — supabase.ts 와 동일 컨벤션. build collect-page-data 에서
// env 누락 시 throw 하면 빌드가 깨지므로 첫 호출 시점에만 검사.

import { S3Client } from '@aws-sdk/client-s3';
import { DeleteObjectCommand, PutObjectCommand } from '@aws-sdk/client-s3';
import { getSignedUrl } from '@aws-sdk/s3-request-presigner';

let _client: S3Client | null = null;

function _getClient(): S3Client {
  if (_client) return _client;

  const endpoint = process.env.R2_ENDPOINT;
  const accessKeyId = process.env.R2_ACCESS_KEY_ID;
  const secretAccessKey = process.env.R2_SECRET_ACCESS_KEY;

  const missing: string[] = [];
  if (!endpoint) missing.push('R2_ENDPOINT');
  if (!accessKeyId) missing.push('R2_ACCESS_KEY_ID');
  if (!secretAccessKey) missing.push('R2_SECRET_ACCESS_KEY');
  if (missing.length > 0) {
    throw new Error(`R2 환경변수 누락: ${missing.join(', ')}. web/.env.local 또는 Vercel env 확인.`);
  }

  _client = new S3Client({
    region: 'auto',
    endpoint,
    credentials: {
      accessKeyId: accessKeyId!,
      secretAccessKey: secretAccessKey!,
    },
    forcePathStyle: true, // R2 wildcard cert 호환 (backend r2_uploader.py 와 동일)
  });
  return _client;
}

export function getR2Bucket(): string {
  const bucket = process.env.R2_BUCKET;
  if (!bucket) {
    throw new Error('R2_BUCKET 환경변수 누락. web/.env.local 또는 Vercel env 확인.');
  }
  return bucket;
}

// 기본 PUT 만료 — 5분. 업로드는 단발이라 짧게. (GET 은 백엔드 1시간 사용 중)
const DEFAULT_PUT_TTL = 300;

export async function presignPut(
  r2Key: string,
  contentType: string = 'video/mp4',
  ttlSec: number = DEFAULT_PUT_TTL,
): Promise<string> {
  const client = _getClient();
  const cmd = new PutObjectCommand({
    Bucket: getR2Bucket(),
    Key: r2Key,
    ContentType: contentType,
  });
  return getSignedUrl(client, cmd, { expiresIn: ttlSec });
}

// 클립 삭제 흐름에서 사용. R2 는 존재하지 않는 key 에 대해서도 success 로 응답
// (idempotent) — 호출 측은 결과 검사 안 해도 OK.
export async function deleteObject(r2Key: string): Promise<void> {
  const client = _getClient();
  await client.send(
    new DeleteObjectCommand({
      Bucket: getR2Bucket(),
      Key: r2Key,
    }),
  );
}
