#!/usr/bin/env node
// 정리 작업 인벤토리 — DB 의 모든 camera_clips 조회 + 159 keep-set 과 diff.
//
// 출력:
// - /tmp/keep-159.txt: 유지할 159 clip_id (이미 생성됨, 검증)
// - /tmp/delete-clips.json: 삭제 대상 [{id, r2_key, thumbnail_r2_key, source, started_at}]
// - 콘솔: 카운트 요약 + 샘플
//
// 사용:
//   cd web && node scripts/inventory-cleanup.mjs
//
// 안전: read-only. 이 스크립트는 아무것도 삭제 안 함. 결과 파일만 작성.

import { createClient } from '@supabase/supabase-js';
import { readFileSync, writeFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, resolve } from 'path';

const __dirname = dirname(fileURLToPath(import.meta.url));

// .env.local 직접 파싱 — dotenv 의존성 안 늘리려고. KEY=VALUE 라인만, 따옴표 처리 안 함.
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

const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL;
const SERVICE_KEY = process.env.SUPABASE_SERVICE_ROLE_KEY;
const DEV_USER_ID = process.env.DEV_USER_ID;
if (!SUPABASE_URL || !SERVICE_KEY || !DEV_USER_ID) {
  console.error('env 누락: NEXT_PUBLIC_SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY / DEV_USER_ID');
  process.exit(1);
}

const sb = createClient(SUPABASE_URL, SERVICE_KEY, {
  auth: { persistSession: false },
});

// 1) keep-set 로드
const keepIds = new Set(
  readFileSync('/tmp/keep-159.txt', 'utf8')
    .split('\n')
    .map((s) => s.trim())
    .filter(Boolean),
);
console.log(`keep-set: ${keepIds.size}`);

// 2) DB 의 모든 clip — page 단위로 (Supabase 기본 1000 row 제한)
const allClips = [];
let from = 0;
const PAGE = 1000;
for (;;) {
  const { data, error } = await sb
    .from('camera_clips')
    .select('id, user_id, r2_key, thumbnail_r2_key, source, started_at')
    .order('started_at', { ascending: false })
    .range(from, from + PAGE - 1);
  if (error) {
    console.error('DB query error:', error);
    process.exit(1);
  }
  if (!data || data.length === 0) break;
  allClips.push(...data);
  if (data.length < PAGE) break;
  from += PAGE;
}
console.log(`total clips in DB: ${allClips.length}`);

// 3) 본인 user_id 필터 — 다른 user 클립 건드리면 안 됨
const myClips = allClips.filter((c) => c.user_id === DEV_USER_ID);
console.log(`my clips (user=${DEV_USER_ID.slice(0, 8)}…): ${myClips.length}`);

// 4) keep / delete 분리
const keep = myClips.filter((c) => keepIds.has(c.id));
const del = myClips.filter((c) => !keepIds.has(c.id));
console.log(`keep (in 159 keep-set): ${keep.length}`);
console.log(`delete candidates: ${del.length}`);

// keep-set 에 있는데 DB 에 없는 ID — 빠진 게 있는지 검증
const keepIdsInDb = new Set(keep.map((c) => c.id));
const missing = [...keepIds].filter((id) => !keepIdsInDb.has(id));
console.log(`keep-set in DB: ${keepIds.size - missing.length} / ${keepIds.size}`);
if (missing.length > 0) {
  console.warn(`⚠ keep-set 중 DB 에 없는 clip ${missing.length}건:`);
  missing.slice(0, 5).forEach((id) => console.warn(`  ${id}`));
  if (missing.length > 5) console.warn(`  ... +${missing.length - 5}건`);
}

// 5) 삭제 대상 통계
const sourceDist = del.reduce((acc, c) => {
  acc[c.source ?? 'null'] = (acc[c.source ?? 'null'] ?? 0) + 1;
  return acc;
}, {});
console.log('delete by source:', sourceDist);

const withR2 = del.filter((c) => c.r2_key).length;
const withoutR2 = del.length - withR2;
console.log(`delete with r2_key: ${withR2}, without: ${withoutR2}`);

// 6) 다른 user 클립 — 절대 안 건드림. 표시만.
const others = allClips.filter((c) => c.user_id !== DEV_USER_ID);
if (others.length > 0) {
  console.log(`(other users' clips, untouched): ${others.length}`);
  // user_id 분포
  const userDist = others.reduce((acc, c) => {
    const k = c.user_id ?? 'null';
    acc[k] = (acc[k] ?? 0) + 1;
    return acc;
  }, {});
  console.log('  user_id dist:');
  Object.entries(userDist)
    .sort(([, a], [, b]) => b - a)
    .slice(0, 5)
    .forEach(([uid, n]) => {
      console.log(`    ${uid?.slice(0, 8) ?? 'null'}…: ${n}`);
    });
}

// 6.5) cameras 테이블 — mirror 설정 확인 (디버깅용)
const { data: cameras, error: camErr } = await sb
  .from('cameras')
  .select('*');
console.log(`\ncameras query: err=${camErr?.message ?? '-'}, rows=${cameras?.length ?? 'null'}`);
if (!camErr && cameras && cameras.length > 0) {
  console.log('  schema keys:', Object.keys(cameras[0]).join(', '));
  cameras.forEach((c) => {
    console.log('  row:', JSON.stringify(c).slice(0, 200));
  });
}

// 7) 결과 파일 저장
writeFileSync('/tmp/delete-clips.json', JSON.stringify(del, null, 2));
console.log(`\nsaved /tmp/delete-clips.json (${del.length} entries)`);
console.log('\n샘플 (first 3):');
del.slice(0, 3).forEach((c) => {
  console.log(`  ${c.id.slice(0, 8)} src=${c.source} r2=${c.r2_key?.slice(0, 30) ?? '-'} ${c.started_at}`);
});
