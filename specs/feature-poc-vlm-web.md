# VLM 행동 분류 PoC — 웹 대시보드 (F1~F3)

> Gemini 2.5 Flash 제로샷이 크레스티드 게코 행동 8클래스를 분류 가능한지 검증하기 위한, **3기능 라벨링 대시보드** 구현. 영상 업로드 / GT 라벨링 / Gemini 호출.

**상태:** 🚧 진행 중 — 인프라 완성. Round 1 실데이터(GT 라벨 + 추론) 대기.
**작성:** 2026-04-26
**연관 SOT:** [`../../tera-ai-product-master/docs/specs/petcam-poc-vlm.md`](../../tera-ai-product-master/docs/specs/petcam-poc-vlm.md) ← 의사결정 16건 + 평가 기준 정의돼 있음. 본 스펙은 그 SOT의 코드 구현 페어.

## 0. 핸드오프 컨텍스트 — 재논의 금지

product-master 세션에서 **확정된 결정 16건**. 새 세션에서 다시 논의하지 말 것. 변경 필요 시 SOT 본 스펙 먼저 갱신.

| # | 결정 |
|---|------|
| 1 | **VLM = Gemini 2.5 Flash** (API key, 구독 모델 아님). `.env` `GEMINI_API_KEY` 이미 세팅됨 |
| 2 | **1라운드 종 = 크레스티드 게코** (카메라 `3a6cffbf-be83-4c77-9fa7-4fcc517c74a6`) |
| 3 | **종은 컨텍스트 입력**. VLM이 영상에서 종을 추론하지 않음. `pets.species` SOT 기반 |
| 4 | **8 행동 클래스**: `eating_paste` / `eating_prey` / `drinking` / `defecating` / `basking` / `hiding` / `moving` / `unseen` |
| 5 | **우선순위 tie-break** (멀티 행동 시 단일 라벨 선택): `eating_prey > eating_paste > drinking > defecating > basking > moving > hiding > unseen` |
| 6 | **데이터 풀 (라운드 1)** = 카메라 2번 motion 17 클립. 부족 시 직접 촬영·유튜브 보충 |
| 7 | **Strategy A** (motion only). idle 검토는 별도 태스크 |
| 8 | **레포 위치** = `petcam-lab/web/` 서브폴더 |
| 9 | **스택** = Next.js 14 App Router + TS + Tailwind, 로컬 실행 |
| 10 | **영상 스토리지** = 1주차 로컬 (`storage/poc-clips/`), 다음 주 R2 |
| 11 | **DB 스키마** = Option A. `camera_clips`에 `source` 컬럼 추가 + `behavior_logs` 신규 |
| 12 | **현재 컬럼명 = `camera_id`** (Stage D3 RENAME 후 UUID, FK to cameras). NOT NULL 해제 필요 |
| 13 | **프롬프트 관리** = 마크다운 (`prompts/system_base.md` + `prompts/species/{species}.md`) |
| 14 | **튜닝 사다리** = (1) 프롬프트 편집 → (2) few-shot → (3) 종 분기 |
| 15 | **단일 라벨, frame_idx=0** (라운드 1 한정. 멀티 라벨은 라운드 2~ 검토) |
| 16 | **성공 기준** = top-1 ≥70% Phase 1 진입 / 50~70% 튜닝 / <50% 전략 재검토 |

## 1. 목적

펫캠 AI 파이프라인의 가장 큰 미지수(VLM 제로샷 정확도)를 영상 수집 인프라와 분리해서 먼저 해소. Phase 1 전략 가능 여부를 1~2주 안에 판가름.

## 2. 스코프

### In
- `web/` 디렉토리에 Next.js 프로젝트 신규
- DB 마이그레이션 (camera_clips 확장 + behavior_logs 신규)
- **F1**: 영상 드래그앤드롭 업로드 + 종 선택 + 로컬 저장 + DB INSERT
- **F2**: video 플레이어 + 8클래스 단축키 라벨 + DB UPDATE
- **F3**: 큐에서 클립 선택 → Gemini 2.5 Flash 호출 → DB INSERT + GT 비교 화면
- 프롬프트 파일 2개 (`system_base.md` + `species/crested_gecko.md`)
- Round 1 평가 (top-1 + confusion matrix + confidence 분포)

### Out
- F4 활동 로그 (Phase 1 운영자 대시보드에서)
- 멀티 사용자/운영자 인증 (PoC는 백승수 1인 로컬)
- R2 마이그레이션 (다음 주 별도)
- VLM 비교 실험 (Claude Vision/GPT-4V — 70% 미달 시에만)
- 가고일 게코 데이터 (라운드 2부터 합류 — 카메라 1번 종 교체 후)

## 3. 완료 조건

### 3-1. 환경 셋업
- [x] `web/` 디렉토리에 Next.js 14 App Router + TS + Tailwind 초기화 (`next@14.2.35`, src-dir, no-eslint)
- [x] 의존성 설치: `@supabase/supabase-js@2.104.1`, `@google/generative-ai@0.24.1`, `react-dropzone@15.0.0`
- [x] `web/.env.local` 작성 (Supabase URL/Service Role Key, Gemini API key, `POC_CLIPS_DIR`)
- [x] `web/.gitignore`에 `/storage/poc-clips/` 추가 (`.env*.local`은 Next.js 기본값에 이미 포함)

> 메모: 루트 `petcam-lab/.gitignore`의 `storage/` 패턴이 이미 `web/storage/` 전체를 잡지만, 의도 명시 위해 `web/.gitignore`에도 별도 등록. 디렉토리 자체는 추적 불가 → 업로드 API가 첫 호출 시 `fs.mkdir({recursive:true})`로 자동 생성.
> ⚠️ npm audit: Next.js 14.2.35에 알려진 DoS/SSRF 취약점 5건. PoC 1주차 로컬 실행이라 노출 없음. R2/배포 단계 진입 시 `next@latest` 업그레이드 검토.

### 3-2. DB 마이그레이션 (Supabase Studio SQL Editor 또는 MCP)
- [x] `ALTER TABLE camera_clips ADD COLUMN source` 실행
- [x] `ALTER TABLE camera_clips ALTER COLUMN camera_id DROP NOT NULL` 실행
- [x] `CREATE TABLE behavior_logs` 실행
- [x] 검증: 기존 17 클립의 `source = 'camera'` 자동 채워짐 확인 (전체 12490개 source='camera', cam2 motion=17)

> 적용: 마이그레이션 `poc_vlm_camera_clips_source_and_behavior_logs` (2026-04-26). `apply_migration` MCP 사용 → 히스토리 등록.

### 3-3. F1 영상 업로드
- [x] `/upload` 페이지: 드래그앤드롭 + 파일 선택 (react-dropzone)
- [x] 종 선택 드롭다운 (4종: crested / gargoyle / leopard / aft) + pet_id (라운드 1은 DEV_PET_ID 자동 부착, UI 노출 X)
- [x] `web/storage/poc-clips/{YYYY-MM-DD}/{uuid}.mp4`로 저장 (API route에서 mkdir recursive)
- [x] `camera_clips` INSERT: `source='upload'`, `camera_id=NULL`, `started_at=업로드 시각`, `file_path`(절대), `duration_sec`(클라이언트 video 메타데이터), `has_motion=true`
- [x] 업로드 후 `/queue`로 리다이렉트

### 3-4. F2 GT 라벨링
- [x] `/queue` 페이지: GT 라벨 없는 클립 목록 (오래된 순, DEV_USER_ID + 라운드1 카메라 OR upload)
- [x] `/clips/{id}/label` 페이지: HTML5 video + 8클래스 버튼 + 메모 필드, 기존 라벨 표시
- [x] 단축키: J/L (±1초), K/Space (재생/정지), 1~8 (라벨 선택), Enter (저장). textarea 포커스 시 무시
- [x] `behavior_logs` INSERT: `source='human'`, `verified=true`, `frame_idx=0`, `created_by=DEV_USER_ID`
- [x] 저장 후 `/queue`로 push → 다음 클립 자동 노출

### 3-5. F3 Gemini 호출
- [x] `prompts/system_base.md` + `prompts/species/crested_gecko.md` 작성 (confidence guide 추가)
- [x] `/inference` 페이지: GT 라벨 있고 VLM 라벨 없는 클립 목록 + 다중 선택
- [x] [선택 일괄 추론] 버튼 → Gemini 2.5 Flash 호출 (직렬, rate limit 회피)
- [x] 응답 JSON 파싱 → `behavior_logs` INSERT (`source='vlm'`, `vlm_model='gemini-2.5-flash'`, `confidence`, `reasoning`, `verified=false`)
- [x] 응답 검증: 8클래스 외 → 실패. 종 가용성 위반 → confidence=0 + `[VALIDATION]` prefix
- [x] `/results` 페이지: GT vs VLM 비교 표 (행 색상: 일치=초록, 불일치=빨강) + confidence

> 검증: `npx next build` 성공 (12 라우트), `npx tsc --noEmit` 통과, dev 서버에서 5 페이지 200 응답. 풀 17 클립 자동 인식.

### 3-6. Round 1 평가
- [ ] 17 클립 GT 라벨 + Gemini 추론 완료
- [ ] Top-1 정확도 산출
- [ ] 8×8 confusion matrix 생성
- [ ] Confidence 분포 (정답 vs 오답)
- [ ] 결과를 product-master `petcam-poc-vlm.md` "리서치/메모" 섹션에 기록
- [ ] Top-1 ≥70% / 50~70% / <50% 분기에 따라 다음 액션 결정

## 4. 설계 메모

### 4-1. DB 마이그레이션 SQL (한 블록 실행)

> Stage D3에서 `camera_uuid` → `camera_id`로 RENAME됨 확인. NOT NULL 제거 + source 컬럼 + behavior_logs 신규.

```sql
-- 1. camera_clips: 업로드 영상 수용
ALTER TABLE camera_clips
  ADD COLUMN source TEXT NOT NULL DEFAULT 'camera'
    CHECK (source IN ('camera', 'upload', 'youtube'));

-- 2. 업로드 영상은 카메라 없음 → NULL 허용
ALTER TABLE camera_clips
  ALTER COLUMN camera_id DROP NOT NULL;

-- 3. behavior_logs 신규 (petcam-ai-pipeline §2-3과 동일)
CREATE TABLE behavior_logs (
  id BIGSERIAL PRIMARY KEY,
  clip_id UUID NOT NULL REFERENCES camera_clips(id) ON DELETE CASCADE,
  frame_idx INT NOT NULL DEFAULT 0,
  action TEXT NOT NULL,
  confidence FLOAT,
  source TEXT NOT NULL CHECK (source IN ('vlm', 'human', 'yolo')),
  vlm_model TEXT,
  reasoning TEXT,
  verified BOOLEAN NOT NULL DEFAULT false,
  corrected_to TEXT,
  notes TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  created_by UUID REFERENCES auth.users(id)
);

CREATE INDEX idx_behavior_logs_clip ON behavior_logs(clip_id);
CREATE INDEX idx_behavior_logs_action ON behavior_logs(action);
CREATE INDEX idx_behavior_logs_source ON behavior_logs(source);

-- 4. 검증
SELECT count(*), source FROM camera_clips GROUP BY source;
-- 기대: 기존 클립 전부 source='camera'
```

### 4-2. Next.js 초기화

```bash
cd /Users/baek/petcam-lab
npx create-next-app@14 web \
  --typescript --tailwind --app --src-dir \
  --import-alias "@/*" --use-npm --no-eslint
cd web
npm install @supabase/supabase-js @google/generative-ai react-dropzone
```

### 4-3. 폴더 구조

```
petcam-lab/web/
├── src/
│   ├── app/
│   │   ├── page.tsx                    ← 홈 (큐 요약 + 네비)
│   │   ├── upload/page.tsx             ← F1
│   │   ├── queue/page.tsx              ← 라벨 대기 큐
│   │   ├── clips/[id]/label/page.tsx   ← F2 라벨링 화면
│   │   ├── inference/page.tsx          ← F3 Gemini 일괄 호출
│   │   ├── results/page.tsx            ← GT vs VLM 비교
│   │   └── api/
│   │       ├── upload/route.ts         ← multipart 업로드 처리
│   │       ├── label/route.ts          ← behavior_logs INSERT (human)
│   │       └── inference/route.ts      ← Gemini 호출 + behavior_logs INSERT (vlm)
│   ├── lib/
│   │   ├── supabase.ts                 ← service role client (server only)
│   │   ├── gemini.ts                   ← Gemini SDK 래퍼
│   │   └── prompts.ts                  ← prompts/*.md 로더
│   └── types.ts                        ← BehaviorClass union, Clip, BehaviorLog
├── prompts/
│   ├── system_base.md
│   └── species/
│       └── crested_gecko.md
├── storage/
│   └── poc-clips/                      ← .gitignore 추가
└── .env.local                          ← .gitignore 추가
```

### 4-4. `.env.local` 내용 (`petcam-lab/.env`에서 복사)

```env
# Supabase (server only — Service Role)
SUPABASE_URL=...
SUPABASE_SERVICE_ROLE_KEY=...

# Gemini
GEMINI_API_KEY=...

# 로컬 스토리지 경로
POC_CLIPS_DIR=/Users/baek/petcam-lab/web/storage/poc-clips
```

### 4-5. 핵심 타입 (`web/src/types.ts`)

```ts
export const BEHAVIOR_CLASSES = [
  'eating_paste',
  'eating_prey',
  'drinking',
  'defecating',
  'basking',
  'hiding',
  'moving',
  'unseen',
] as const;
export type BehaviorClass = typeof BEHAVIOR_CLASSES[number];

export const SPECIES = ['crested_gecko', 'gargoyle_gecko', 'leopard_gecko', 'aft'] as const;
export type Species = typeof SPECIES[number];

// 종별 클래스 가용성 (eating_paste는 일부 종만)
export const SPECIES_CLASSES: Record<Species, BehaviorClass[]> = {
  crested_gecko: [...BEHAVIOR_CLASSES],          // 전체 8
  gargoyle_gecko: [...BEHAVIOR_CLASSES],          // 전체 8
  leopard_gecko: BEHAVIOR_CLASSES.filter(c => c !== 'eating_paste'),
  aft: BEHAVIOR_CLASSES.filter(c => c !== 'eating_paste'),
};
```

### 4-6. Gemini 호출 (`web/src/lib/gemini.ts`)

```ts
import { GoogleGenerativeAI } from '@google/generative-ai';
import fs from 'node:fs/promises';

const genAI = new GoogleGenerativeAI(process.env.GEMINI_API_KEY!);
const model = genAI.getGenerativeModel({ model: 'gemini-2.5-flash' });

export async function classifyClip(args: {
  videoPath: string;
  species: Species;
  systemPrompt: string;   // prompts/system_base.md + species/{species}.md 합친 결과
}): Promise<{ action: BehaviorClass; confidence: number; reasoning: string }> {
  const videoBytes = await fs.readFile(args.videoPath);
  const result = await model.generateContent([
    args.systemPrompt,
    {
      inlineData: {
        mimeType: 'video/mp4',
        data: videoBytes.toString('base64'),
      },
    },
  ]);
  const text = result.response.text();
  // JSON 파싱 (모델이 ```json 블록으로 감쌀 수 있어 정규식 추출)
  const match = text.match(/\{[\s\S]*\}/);
  if (!match) throw new Error(`No JSON in Gemini response: ${text}`);
  return JSON.parse(match[0]);
}
```

> **주의**: Gemini File API 쓰면 큰 영상 효율적이지만 PoC 1주차는 inline base64로 충분 (60초 mp4 ~5MB). 라운드 2 R2 도입 후 File API 검토.

### 4-7. 프롬프트 초기 내용

**`prompts/system_base.md`** (모든 종 공통):

```markdown
You are a herpetology behavior classifier for pet reptiles. Watch the video carefully and classify the dominant behavior.

# Output (JSON only, no prose)
{"action": "<class>", "confidence": 0.0-1.0, "reasoning": "<one sentence in English>"}

# Behavior classes (choose ONE)
{available_classes_block}

# If multiple behaviors appear, use this priority:
eating_prey > eating_paste > drinking > defecating > basking > moving > hiding > unseen

# Species context
Species: {species_name}
{species_specific_notes}
```

**`prompts/species/crested_gecko.md`**:

```markdown
species_name: Crested Gecko (Correlophus ciliatus)

available_classes:
  - eating_paste: licking fruit puree (CGD/MRP/Pangea/Repashy) from a small dish. Tongue extends repeatedly, body usually still
  - eating_prey: actively hunting/biting live insects (crickets, dubia roaches). Open-mouth lunge, fast head movement
  - drinking: licking water droplets off leaves/glass or from a dish
  - defecating: tail base lifts, white-tipped feces extruded, often on a perch
  - basking: motionless under heat source (UVB/halogen). Crested geckos are not strong baskers — usually low effort, near hide
  - hiding: inside coco hide, plant cover, or hammock. Body partially or fully obscured
  - moving: general locomotion — climbing, walking on substrate, jumping. No specific feeding/drinking/defecation
  - unseen: animal not visible in frame at all

species_specific_notes: |
  Crested geckos are nocturnal, arboreal. They lack eyelids and lick their eyes — do NOT classify eye-licking as drinking.
  CGD paste is the standard diet (~80% of feeding). Live prey is occasional.
  Adult lily axanthic morph in this footage: pale yellow base, reduced pigmentation, dark pinstripe.
```

### 4-8. 프롬프트 로더 (`web/src/lib/prompts.ts`)

```ts
import fs from 'node:fs/promises';
import path from 'node:path';
import { Species, SPECIES_CLASSES } from '@/types';

export async function buildSystemPrompt(species: Species): Promise<string> {
  const base = await fs.readFile(path.join(process.cwd(), 'prompts', 'system_base.md'), 'utf8');
  const speciesFile = await fs.readFile(
    path.join(process.cwd(), 'prompts', 'species', `${species}.md`),
    'utf8'
  );
  // species file 파싱 (간단 yaml-ish — name/notes/classes 분리)
  const classes = SPECIES_CLASSES[species]
    .map(c => `- ${c}`)
    .join('\n');
  return base
    .replace('{available_classes_block}', classes)
    .replace('{species_name}', species)
    .replace('{species_specific_notes}', speciesFile);
}
```

> **단순화**: 라운드 1은 species file을 통째로 species_specific_notes에 박아넣음. 라운드 2~에서 정식 yaml/frontmatter 파싱으로 격상.

### 4-9. F3 응답 검증

Gemini 응답 클래스가 8개 중 하나가 아니면 reject + log. 종별 가용 클래스(예: leopard 게코는 eating_paste 불가)와 매칭 안 되면 confidence 강제 0 처리 + reasoning에 `[VALIDATION] species mismatch` prefix.

### 4-10. 평가 산출 (스크립트)

`web/scripts/evaluate.ts` (또는 별도 SQL 노트북):

```sql
-- Top-1 정확도
SELECT
  count(*) FILTER (
    WHERE h.action = v.action
  )::float / count(*) AS top1_accuracy
FROM behavior_logs h
JOIN behavior_logs v ON h.clip_id = v.clip_id
WHERE h.source = 'human' AND v.source = 'vlm';

-- Confusion matrix
SELECT h.action AS gt, v.action AS pred, count(*)
FROM behavior_logs h
JOIN behavior_logs v ON h.clip_id = v.clip_id
WHERE h.source = 'human' AND v.source = 'vlm'
GROUP BY h.action, v.action
ORDER BY h.action, count(*) DESC;

-- Confidence 분포 (정답/오답)
SELECT
  CASE WHEN h.action = v.action THEN 'correct' ELSE 'wrong' END AS verdict,
  round(v.confidence::numeric, 1) AS conf_bucket,
  count(*)
FROM behavior_logs h
JOIN behavior_logs v ON h.clip_id = v.clip_id
WHERE h.source = 'human' AND v.source = 'vlm'
GROUP BY verdict, conf_bucket
ORDER BY conf_bucket DESC, verdict;
```

### 4-11. 선택한 방법 vs 대안

- **Next.js API Routes vs FastAPI 분리**: 라운드 1은 단일 프로세스(Next.js)로. Phase 1 운영자 대시보드 가면 FastAPI(petcam-lab)와 분리 — auth/RLS 무게 때문
- **로컬 fs vs R2**: 베타 5명 + 17 클립이라 로컬로 충분. R2는 다음 주 별도
- **Service Role Key 노출 위험**: API Routes(서버 코드)에서만 사용. 클라이언트에는 절대 안 노출
- **Gemini File API vs inline base64**: 60초 mp4 ~5MB라 inline 충분. >20MB 영상 들어오면 File API로 전환

### 4-12. 리스크

| 리스크 | 대응 |
|------|------|
| Gemini 응답이 JSON 아닌 prose로 옴 | 정규식 fallback + 재시도 1회. 그래도 실패 시 manual 처리 큐 |
| 17 클립으로 confusion matrix 의미 부족 | 라운드 2 50개+로 확장 (카메라 1번 + 직접 촬영) |
| `eating_paste` vs `eating_prey` 영상에 둘 다 거의 없을 수 있음 | 직접 급식 시 촬영 보충 (사료 그릇 + 귀뚜라미 케이스) |
| 단일 라벨이 한계 — 1 클립에 여러 행동 | 라운드 1은 우선순위 tie-break, 라운드 2~에서 멀티 라벨 검토 |

## 5. 학습 노트

- **Next.js App Router + Server Actions/Route Handlers**: API Routes(`app/api/*/route.ts`)가 Express handler 같은 역할. `request.formData()`로 multipart 받기
- **Supabase Service Role**: RLS 우회. 운영자 대시보드 같은 백엔드 도구에서만 사용. 클라이언트 직접 노출 금지 — 항상 서버 코드에서 fetch wrapping
- **Gemini SDK `inlineData`**: base64 인코딩한 mp4를 multimodal input으로 함께 전송. 파일 크기 제한 ~20MB (실측). 이상은 File API 또는 사전 압축
- **react-dropzone**: 드래그앤드롭 hook. `useDropzone({ accept: { 'video/mp4': [] } })`로 mp4만 받기
- **camera_clips ON DELETE CASCADE**: 클립 삭제 시 behavior_logs 자동 삭제. 데이터 일관성 자동
- **PostgreSQL `ALTER COLUMN ... DROP NOT NULL`**: 기존 데이터 영향 없음. 새 NULL 행만 추가 가능. 즉시 실행 가능 (기존 D3 마이그레이션 패턴과 동일)

## 6. 참고

- **SOT 본 스펙**: [`../../tera-ai-product-master/docs/specs/petcam-poc-vlm.md`](../../tera-ai-product-master/docs/specs/petcam-poc-vlm.md) — 의사결정 + 평가 기준
- **AI 파이프라인 본체**: [`../../tera-ai-product-master/docs/specs/petcam-ai-pipeline.md`](../../tera-ai-product-master/docs/specs/petcam-ai-pipeline.md) §2-3 behavior_logs DDL 원본
- **Phase 1 운영자 대시보드 (확장 페어)**: [`../../tera-ai-product-master/docs/specs/petcam-labeling-dashboard.md`](../../tera-ai-product-master/docs/specs/petcam-labeling-dashboard.md) — F4 활동 로그 + 다중 운영자 인증은 여기서
- **D3 컬럼 RENAME 이력**: [`./stage-d3-multi-capture.md`](./stage-d3-multi-capture.md) `camera_uuid` → `camera_id`
- **Gemini Vision 공식 문서**: https://ai.google.dev/gemini-api/docs/vision
- **Next.js 14 App Router**: https://nextjs.org/docs/app

## 7. 진행 순서 (다음 세션 핸드오프)

1. **마이그레이션** (4-1 SQL 블록) — Supabase MCP `execute_sql` 또는 Studio SQL Editor
2. **Next.js 초기화** (4-2 명령) — `web/` 폴더 생성
3. **`.env.local` 작성** (4-4) + `.gitignore` 업데이트 (`web/storage/poc-clips/`, `web/.env.local`)
4. **타입 + 라이브러리** (4-5, 4-6, 4-8) — `src/types.ts`, `lib/gemini.ts`, `lib/prompts.ts`
5. **프롬프트 파일** (4-7) — `prompts/system_base.md`, `prompts/species/crested_gecko.md`
6. **F1 업로드** — `app/upload/page.tsx` + `app/api/upload/route.ts`
7. **F2 라벨링** — `app/queue/page.tsx`, `app/clips/[id]/label/page.tsx`, `app/api/label/route.ts`
8. **F3 추론** — `app/inference/page.tsx`, `app/api/inference/route.ts`
9. **결과 화면** — `app/results/page.tsx` (4-10 SQL 활용)
10. **Round 1 실행** — 17 클립 GT 라벨 → 일괄 추론 → 평가 → product-master 본 스펙 메모 갱신
