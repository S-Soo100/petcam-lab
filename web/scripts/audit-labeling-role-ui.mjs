#!/usr/bin/env node
// 정적 fail-closed 감사 — 역할 셸/내비게이션이 반응형·잘림 방지 계약(설계 §9)과 역할당 3메뉴
// 규칙(설계 §3)을 지키는지 문자열 토큰으로 동결한다. 전체 레포가 아니라 셸/내비 파일만 스캔해
// 과거 화면이 false positive 를 내지 않게 한다(계획 Task 8 Step 3).
//
// 실행: npm run audit:labeling-role-ui (exit 0 = 통과, exit 1 = 위반).

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const webRoot = join(dirname(fileURLToPath(import.meta.url)), '..');
const read = (rel) => readFileSync(join(webRoot, rel), 'utf8');

const shell = read('src/app/labeling/_role-shell.tsx');
const layout = read('src/app/labeling/layout.tsx');
const nav = read('src/lib/labelingRoleNavigation.ts');

const errors = [];

// 1) 반응형·잘림 방지 토큰이 셸에 모두 있어야 한다(설계 §9).
const required = [
  'min-w-0',
  'whitespace-nowrap',
  'overflow-x-clip',
  'grid-cols-3',
  'bottom-0',
  'lg:grid-cols-[220px_minmax(0,960px)]',
];
const shellAndLayout = `${shell}\n${layout}`;
for (const token of required) {
  if (!shellAndLayout.includes(token)) {
    errors.push(`반응형 토큰 누락: ${token}`);
  }
}

// 2) 셸에 폐기된 옛 메뉴 라벨이 남아 있으면 안 된다(역할별 3메뉴로 재편, 설계 §3).
const retiredLabels = ['큐', '내 라벨', '라우터 리뷰', '격리함', '그룹 배정'];
for (const label of retiredLabels) {
  if (shell.includes(label)) {
    errors.push(`셸에 폐기된 라벨 잔존: ${label}`);
  }
}

// 3) 역할당 업무 메뉴는 최대 3개(설계 §3). NAV 항목 리터럴(label: '...')은 3(라벨러)+3(Owner)=6 이하.
//    타입 정의(label: string)는 따옴표가 없어 제외된다.
const labelCount = (nav.match(/label:\s*'/g) || []).length;
if (labelCount > 6) {
  errors.push(`역할 내비 항목이 3개를 초과했어(labels=${labelCount}, 최대 6).`);
}

if (errors.length > 0) {
  console.error('[audit:labeling-role-ui] 위반 발견:');
  for (const e of errors) console.error(`  - ${e}`);
  process.exit(1);
}

console.log('[audit:labeling-role-ui] 통과 — 역할 셸 반응형·3메뉴 계약 OK');
