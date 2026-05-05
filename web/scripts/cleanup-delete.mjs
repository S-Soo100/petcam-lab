#!/usr/bin/env node
// 정리 작업 실행 — /tmp/delete-clips.json 의 N건을 batch 로 삭제.
//
// 전제:
// - inventory-cleanup.mjs 가 먼저 실행되어 /tmp/delete-clips.json 생성됨.
// - 백엔드 캡처 중지됨 (specs/next-session.md 의 "백엔드 캡처 일시 중지").
//
// 사용:
//   node scripts/cleanup-delete.mjs --dry         # 1 chunk 만 시뮬레이션 (DB/R2 안 건드림)
//   node scripts/cleanup-delete.mjs --confirm     # 실 실행
//
// 동작:
// 1. /tmp/delete-clips.json 로드 → 1000건 chunk 로 분할
// 2. 각 chunk:
//    a. R2 키 (mp4 + thumb) 모음 → DeleteObjects batch (S3 SDK 1 호출당 1000개 한도)
//    b. behavior_labels.delete().in('clip_id', chunk_ids)
//    c. behavior_logs.delete().in('clip_id', chunk_ids)
//    d. camera_clips.delete().in('id', chunk_ids)
// 3. 진행률 + 에러 누적 출력
//
// 안전장치:
// - --confirm 없으면 dry-run.
// - 1 chunk 마다 진행 상황 출력 → 중간에 Ctrl-C 가능, 다음 실행에서 재개 가능
//   (재개는 inventory 다시 돌려서 새 delete-clips.json 만들면 됨 — 이미 지운 건 skip).

import { createClient } from '@supabase/supabase-js';
import { S3Client, DeleteObjectsCommand } from '@aws-sdk/client-s3';
import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, resolve } from 'path';

const __dirname = dirname(fileURLToPath(import.meta.url));

function loadDotEnv(path) {
  const text = readFileSync(path, 'utf8');
  for (const line of text.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const eq = trimmed.indexOf('=');
    if (eq <= 0) continue;
    const k = trimmed.slice(0, eq).trim();
    let v = trimmed.slice(eq + 1).trim();
    if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) {
      v = v.slice(1, -1);
    }
    if (!(k in process.env)) process.env[k] = v;
  }
}
loadDotEnv(resolve(__dirname, '..', '.env.local'));

const args = process.argv.slice(2);
const DRY = !args.includes('--confirm');
const ONLY_FIRST_CHUNK = args.includes('--dry');

const SB_URL = process.env.NEXT_PUBLIC_SUPABASE_URL;
const SB_KEY = process.env.SUPABASE_SERVICE_ROLE_KEY;
const R2_ENDPOINT = process.env.R2_ENDPOINT;
const R2_AKID = process.env.R2_ACCESS_KEY_ID;
const R2_SK = process.env.R2_SECRET_ACCESS_KEY;
const R2_BUCKET = process.env.R2_BUCKET;
for (const [k, v] of Object.entries({
  NEXT_PUBLIC_SUPABASE_URL: SB_URL,
  SUPABASE_SERVICE_ROLE_KEY: SB_KEY,
  R2_ENDPOINT,
  R2_ACCESS_KEY_ID: R2_AKID,
  R2_SECRET_ACCESS_KEY: R2_SK,
  R2_BUCKET,
})) {
  if (!v) {
    console.error(`env 누락: ${k}`);
    process.exit(1);
  }
}

const sb = createClient(SB_URL, SB_KEY, { auth: { persistSession: false } });
const s3 = new S3Client({
  region: 'auto',
  endpoint: R2_ENDPOINT,
  credentials: { accessKeyId: R2_AKID, secretAccessKey: R2_SK },
  forcePathStyle: true,
});

const all = JSON.parse(readFileSync('/tmp/delete-clips.json', 'utf8'));
console.log(`load ${all.length} delete candidates`);
console.log(`mode: ${DRY ? 'DRY-RUN' : 'CONFIRM'} ${ONLY_FIRST_CHUNK ? '(first chunk only)' : ''}`);
if (DRY) console.log('아무것도 안 지움 — --confirm 없음.');

// PostgREST `in.()` URL 길이 한도 — UUID 36자 × N + 다른 요소 → 1000건은 Bad Request.
// 100 으로 줄임. R2 DeleteObjects 는 1000개 batch 별도 처리 (아래 i+=1000 loop).
const CHUNK = 100;
const chunks = [];
for (let i = 0; i < all.length; i += CHUNK) chunks.push(all.slice(i, i + CHUNK));
console.log(`chunks: ${chunks.length} × ${CHUNK}`);

const stats = {
  r2_deleted: 0,
  r2_errors: [],
  labels_deleted: 0,
  logs_deleted: 0,
  clips_deleted: 0,
  chunks_done: 0,
};

const targetChunks = ONLY_FIRST_CHUNK ? chunks.slice(0, 1) : chunks;

for (let ci = 0; ci < targetChunks.length; ci++) {
  const chunk = targetChunks[ci];
  const ids = chunk.map((c) => c.id);
  const r2Keys = [];
  for (const c of chunk) {
    if (c.r2_key) r2Keys.push({ Key: c.r2_key });
    if (c.thumbnail_r2_key) r2Keys.push({ Key: c.thumbnail_r2_key });
  }

  const t0 = Date.now();

  // a) R2 batch delete — DeleteObjects 1 호출당 1000 한도. r2Keys 가 1000 넘을 일은 없지만 (1 chunk = 1000 clips * 2 keys = 2000) 분할.
  if (r2Keys.length > 0) {
    if (DRY) {
      stats.r2_deleted += r2Keys.length;
    } else {
      for (let i = 0; i < r2Keys.length; i += 1000) {
        const batch = r2Keys.slice(i, i + 1000);
        try {
          const resp = await s3.send(
            new DeleteObjectsCommand({
              Bucket: R2_BUCKET,
              Delete: { Objects: batch, Quiet: true },
            }),
          );
          stats.r2_deleted += batch.length - (resp.Errors?.length ?? 0);
          if (resp.Errors && resp.Errors.length > 0) {
            stats.r2_errors.push(...resp.Errors.map((e) => `${e.Key}: ${e.Message}`));
          }
        } catch (e) {
          stats.r2_errors.push(`batch ${i}: ${e.message}`);
        }
      }
    }
  }

  // b) behavior_labels
  if (!DRY) {
    const { error: labErr, count: labCount } = await sb
      .from('behavior_labels')
      .delete({ count: 'exact' })
      .in('clip_id', ids);
    if (labErr) {
      console.error(`chunk ${ci} behavior_labels error:`, labErr.message);
    } else {
      stats.labels_deleted += labCount ?? 0;
    }
  }

  // c) behavior_logs
  if (!DRY) {
    const { error: logErr, count: logCount } = await sb
      .from('behavior_logs')
      .delete({ count: 'exact' })
      .in('clip_id', ids);
    if (logErr) {
      console.error(`chunk ${ci} behavior_logs error:`, logErr.message);
    } else {
      stats.logs_deleted += logCount ?? 0;
    }
  }

  // d) camera_clips
  if (!DRY) {
    const { error: clipErr, count: clipCount } = await sb
      .from('camera_clips')
      .delete({ count: 'exact' })
      .in('id', ids);
    if (clipErr) {
      console.error(`chunk ${ci} camera_clips error:`, clipErr.message);
      // 멈추는 게 안전 — DB row 가 안 지워졌으면 R2 만 지워진 상태가 되어 재개 어려움.
      console.error('STOPPING due to camera_clips delete error');
      break;
    } else {
      stats.clips_deleted += clipCount ?? 0;
    }
  } else {
    // dry-run 도 카운트 시뮬
    stats.clips_deleted += ids.length;
    stats.labels_deleted += ids.length; // upper bound
    stats.logs_deleted += ids.length;
  }

  stats.chunks_done++;
  const dt = ((Date.now() - t0) / 1000).toFixed(2);
  console.log(
    `chunk ${ci + 1}/${targetChunks.length} done in ${dt}s — clips=${stats.clips_deleted} labels=${stats.labels_deleted} logs=${stats.logs_deleted} r2=${stats.r2_deleted}${stats.r2_errors.length > 0 ? ` r2_err=${stats.r2_errors.length}` : ''}`,
  );
}

console.log('\n=== summary ===');
console.log(`mode: ${DRY ? 'DRY-RUN' : 'CONFIRM'}`);
console.log(`chunks: ${stats.chunks_done}/${targetChunks.length}`);
console.log(`R2 objects deleted: ${stats.r2_deleted}`);
console.log(`behavior_labels: ${stats.labels_deleted}`);
console.log(`behavior_logs: ${stats.logs_deleted}`);
console.log(`camera_clips: ${stats.clips_deleted}`);
if (stats.r2_errors.length > 0) {
  console.log(`R2 errors: ${stats.r2_errors.length}`);
  stats.r2_errors.slice(0, 5).forEach((e) => console.log(`  ${e}`));
}
