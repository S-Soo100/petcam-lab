# VLM 행동 분류 PoC — 웹 대시보드 (F1~F3)

> Gemini 2.5 Flash 제로샷이 크레스티드 게코 행동 9클래스를 분류 가능한지 검증하기 위한, **3기능 라벨링 대시보드** 구현. 영상 업로드 / GT 라벨링 / Gemini 호출.

**상태:** ✅ Round 3 종료 — v3.5 85.5% **production 확정**. baseline 깨기 시도 3회 모두 퇴행 (v3.6 -1.9 / v3.7-B -5.0 / v4 clean-slate -6.9%p, 2026-04-30). 잔존 오답은 prompt 한계 아닌 시각 한계로 결론, 다음은 UX 통합·메타데이터·HITL 정공법.
**작성:** 2026-04-26 / **갱신:** 2026-04-30 (Round 3 종료)
**연관 SOT:** [`../../tera-ai-product-master/docs/specs/petcam-poc-vlm.md`](../../tera-ai-product-master/docs/specs/petcam-poc-vlm.md) ← 의사결정 16건 + 평가 기준 정의돼 있음. 본 스펙은 그 SOT의 코드 구현 페어.

## 0. 핸드오프 컨텍스트 — 재논의 금지

product-master 세션에서 **확정된 결정 16건**. 새 세션에서 다시 논의하지 말 것. 변경 필요 시 SOT 본 스펙 먼저 갱신.

| # | 결정 |
|---|------|
| 1 | **VLM = Gemini 2.5 Flash** (API key, 구독 모델 아님). `.env` `GEMINI_API_KEY` 이미 세팅됨 |
| 2 | **1라운드 종 = 크레스티드 게코** (카메라 `3a6cffbf-be83-4c77-9fa7-4fcc517c74a6`) |
| 3 | **종은 컨텍스트 입력**. VLM이 영상에서 종을 추론하지 않음. `pets.species` SOT 기반 |
| 4 | ~~9 행동 클래스 (v3.4)~~ → **8 행동 클래스 (v3.5부터)**: `eating_paste` / `eating_prey` / `drinking` / `defecating` / `shedding` / `basking` / `moving` / `unseen` (hiding 폐기, SOT 결정 #18) |
| 5 | **우선순위 tie-break** (멀티 행동 시 단일 라벨 선택): `eating_prey > eating_paste > drinking > defecating > shedding > basking > moving > unseen` |
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

### 3-6. Round 1 평가 (1차, 2026-04-26)
- [x] 17 클립 (cam2 motion) + 3 클립 (직접 촬영 주사기 급여) GT 라벨 완료 → 총 **20건**
- [x] Top-1 정확도 산출 → **85.0% (17/20)** ✅ Phase 1 진입 기준 (≥70%) 충족
- [x] 8×8 confusion matrix 생성 (`/results` 페이지)
- [x] Confidence 분포 (정답 vs 오답) (`/results` 페이지)
- [x] 결과를 product-master `petcam-poc-vlm.md` "리서치/메모" 섹션에 기록
- [x] 분기 결정: **Phase 1 진입 검토 단계 진입**. 데이터 다양성 보강 후 2차 평가 예정

#### 프롬프트 진화 (Round 1 내부)
| 버전 | 정확도 | 변경 요지 |
|---|---|---|
| v1 (초안) | — | 클래스 정의만, 검증 안함 |
| v2 | 13/17 = 76.5% | "tongue contact" 룰 추가 |
| v3 | 12/17 = 70.6% | eating_paste hallucination 0건 ✅ but unseen 과민 (<20% rule) ❌ |
| v3.1 | 17/20 = 85.0% | unseen 룰 완화 + eating_paste 강화 유지 |
| v3.1 + GT 재라벨 (76건) | 58/76 = 76.3% | 데이터 보강 (drinking·hiding·unseen 케이스 +56건). 76.3%가 새 baseline |
| v3.2 | 56/76 = **73.7% ↓** | Rule 7 "타임스탬프 명시 필수" 추가 → **퇴행** |
| v3.3 (정정 전 GT) | 59/76 = 77.6% | Rule 7 제거 (confabulation booster), Rule 8(transparency) 유지, `temperature: 0.1` 명시 |
| **v3.3 (정정 GT, 현재)** | **62/76 = 81.6%** | GT 재검토로 3건 정정. 잔존 14건 중 9건은 same-error (모델 키워도 안 풀림) |

#### v3.2 사고 — "근거 강제 룰"이 환각을 부풀린다
- **현상**: Rule 7 ("타임스탬프와 함께 근거를 적어라") 추가 후 broken 4건 + still_wrong 13건. recovered 7건은 유리한 케이스(moving를 eating_paste로 잘못 고집하던 패턴)만 잡음.
- **공통 패턴**: 모델이 오답을 정당화하기 위해 가짜 timestamp 만들어냄. 예: "12초경 밥그릇 앞으로 가는것 확인. 하지만 먹는 모습은 보이지 않음" → 그래놓고 `eating_paste 0.95`. timestamp는 자신감 부풀리기 도구로 변질.
- **외부 critic 교차 검증** (donts.md 6번 룰):
  - Codex GPT-5: "evidence-forcing rules는 confabulation booster"
  - Gemini: 동일 결론. 시각적 prior(geko + 그릇 한 프레임) → feeding 분류 strong bias.
- **수정**: v3.3에서 Rule 7 제거. Rule 8 (transparency disambiguation: 투명 표면=drinking, 불투명=eating_paste)만 유지. confidence 가이드는 강화하지 않음 — 이미 "tongue contact 명시 + sustained licks 룰"로 충분.
- **Lock-in**: `gemini.ts`에 `temperature: 0.1, topP: 0.95, responseMimeType: 'application/json'` 박음. 기본 1.0 = 같은 클립 호출마다 답 흔들림(drinking↔moving) 확인.
- **donts 등재**: [`.claude/rules/donts/vlm.md`](../.claude/rules/donts/vlm.md) 룰 5, 6.

#### Pro 모델 검증 결과 (2026-04-28 완료)
- **목적**: 잔존 mismatch가 Flash 한계인지, VLM 일반의 한계(시각적 prior bias)인지 분리.
- **방법**: Gemini 2.5 Pro로 같은 76건 + 같은 v3.3 prompt + 같은 generationConfig 추론. DB INSERT 안 함 → JSONL.
- **정확도**: Flash 59/76 = **77.6%** vs Pro 56/76 = **73.7%** (Pro가 **-3.9%p** 나쁨).
- **5 카테고리**: held-correct 54 / recovered 2 / **broken 5** / still-wrong 15 (same-error 12 + diff-error 3) / missing 0.
- **결정**:
  1. ❌ **Pro 운영 도입 보류**. 비용 5배 + 정확도 손해. broken 5건 모두 `moving → eating_paste` 방향 — Pro는 시각적 prior에 더 확신을 갖고 단언 ("repeatedly licking...for sustained period" 신뢰도 0.95~1.00). Flash가 더 보수적.
  2. ✅ **잔존 mismatch는 VLM 일반 한계**. same-error 12건 = 모델 크기 키워도 동일 오답. 프롬프트 개선 천장 ~75~78% 근처.
  3. ⚠️ **GT 재검토 필요 케이스 4건**: `179fcb85`/`332b93ce` (unseen↔moving 경계), `1334b95c`/`65b57205` (moving이 GT지만 둘 다 eating_paste로 단언 + 사용자 노트 비어있음).
- **다음 단계 우선순위**: (a) 의심 GT 4건 재시청 → 확정 → 실제 천장 측정, (b) basking/defecating/eating_prey 데이터 보강 (현재 0~1건), (c) few-shot 도입 (prompt 개선보다 ROI 높음).
- **결과 리포트**: `/tmp/compare-report.md`. 스크립트: `/tmp/infer-pro.py`, `/tmp/compare-flash-pro.py`.

#### same-error 패턴 (모델 키워도 안 풀리는 핵심 12건)
| 방향 | 건수 | 해석 |
|---|---|---|
| `moving` → `eating_paste` | 4 | 그릇 근처에서 inspect만 해도 모델은 feeding 단언 — visual prior bias |
| `unseen` → `moving` | 2 | 꼬리 끝/잠깐 출현 케이스 — 정의 모호, GT 자체 의심 |
| `hiding` → `moving` | 2 | 클립 일부만 hiding — 단일 라벨 한계 |
| `eating_paste` → `moving` | 1 | feeding 시작 직전 클립이라 모델 보수적 — 시간 경계 문제 |
| `drinking` → `moving` | 1 | 벽면 한 번 lick — 모델은 1회 lick = 단순 환경 sensing으로 처리 |
| `moving` → `drinking` | 1 | 벽면 lick 1회 잡았지만 GT는 sensing으로 본 케이스 — 양방향 모호 |
| `eating_prey` → `moving` | 1 | 데이터 1건뿐 — 통계적 의미 미약 |

#### 남은 mismatch 3건 (전부 정의/판단 모호)
- `179fcb85`: GT=moving, VLM=eating_paste (conf 0.95) — **GT 의심**, 영상 재시청 시 GT 수정 후보
- `556a7bfe`: GT=hiding, VLM=moving — `hiding` 정의("inside hide AND stationary") 충돌, 사용자 노트는 "은신처로 들어가 고개 돌리고 혀 1번"
- `332b93ce`: GT=unseen, VLM=moving (conf 0.6) — VLM 본인도 모호 인정, unseen vs moving 경계

#### Phase 1 진입 결론
- ✅ Top-1 85% — 기준 충족
- ✅ eating_paste 정확도 100% (3/3, 주사기·스틱 변형도 정확)
- ⚠️ 데이터 다양성 부족 — 17건 중 14건이 GT=moving. drinking/basking/defecating 검증 0건
- → **2차 평가**: 다양성 데이터 추가 후 재측정

### 3-7. Round 1 2차 평가 (데이터 다양성 보강)
- [x] hiding 명확 케이스 영상 추가 (cocohut 등 hide 안 stationary) — GT 76건에 포함
- [ ] basking 케이스 영상 추가 — 사용자 별도 촬영 예정 (내일까지)
- [x] drinking 케이스 영상 추가 — 7건 확보
- [ ] defecating 케이스 영상 추가
- [ ] eating_prey 케이스 영상 추가 — 1건 확보 (`eating_prey3.mov`)
- [x] `179fcb85`, `332b93ce` GT 재검토 (영상 재시청) — 사용자 전수 GT 재라벨 + 코멘트 부착 완료
- [ ] 클래스별 정확도 표 작성 (Top-1만으로는 다양성 못 봄)
- [ ] 2차 평가 결과 SOT 갱신
- [x] Flash baseline lock-in (1차): v3.3 + temperature 0.1 = 59/76 = 77.6%
- [x] Pro 76건 검증 결과 분석 → 5카테고리 분류 + 결정 트리 → **Pro 도입 보류 결정** (Flash 77.6% > Pro 73.7%)
- [x] GT 재검토 4건 → 3건 정정 (1번 `179fcb85` unseen→moving / 2번 `332b93ce` unseen→moving / 4번 `65b57205` moving→eating_paste). 3번 `1334b95c`는 moving 유지.
- [x] **Flash baseline (2차, 정정 GT)**: 62/76 = **81.6%** (+4.0%p), Pro: 59/76 = 77.6% (+3.9%p). Pro 결론은 동일 — 보류.
- [ ] basking 데이터 추가 후 v3.3 위에서 회귀 검증
- [ ] few-shot prompt 도입 검토 (prompt 추가 개선보다 ROI 높음)

#### GT 재검토 메타 인사이트 (2026-04-28)
- 의심 4건 중 **3건이 모델 답대로 GT 정정됨** (사용자가 자기 GT를 모델 의견에 맞춰 수정).
- 시사점: GT는 안정적인 ground truth가 아님. 모델이 사람보다 정확한 영역 존재 (특히 "꼬리만 잠깐 보임" 같은 unseen↔moving 경계, 카메라 각도상 paste 핥는 것처럼 보이는 케이스).
- 실용적 함의: 향후 평가 시 GT vs 모델 단순 일치율만 보지 말고, **모델이 GT보다 자신감 있게 다른 답을 단언하는 케이스는 재검토 큐**로 분류해서 GT 정정 루프 도입.

### 3-8. Round 1 3차 평가 (v3.4 — shedding 클래스 추가 + 105건 확장)

#### 트리거
- v3.3 4-shot이 GT 재검수 후 +3.9%p 효과 확인 (broken 13건 GT 검수에서 7건 정정 → 0-shot 69.7%, 4-shot 73.6%).
- inbox/0429에 16건 신규 영상 (탈피 4건, 사냥 7건, 배변 3건, 페이스트 2건). **탈피는 기존 8 클래스로 라벨링 불가** → 9번째 클래스 `shedding` 정식 도입.
- 평가셋: 89 → 105건. 통계 robustness 향상.

#### Phase 1: v3.4 prompt 작성 (shedding 추가)
- `system_base.md` Rule 8/9 추가: shedding 직접 증거(피부 제거 행동) 요구, shedding-vs-eating 모호성 해소(탈피 중 허물 씹기는 shedding으로).
- `species/crested_gecko.md`: shedding 클래스 정의 + 종 노트 (2-4주 주기, pre-shed vs active-shed, 허물 섭취).
- 우선순위: `eating_prey > eating_paste > drinking > defecating > shedding > basking > moving > hiding > unseen`.
- `types.ts` `BEHAVIOR_CLASSES` / `PRIORITY_ORDER` + label UI 핫키 1~9 확장.

#### Phase 2: inbox/0429 16건 import
- ffmpeg .mov→.mp4 변환 (libx264, crf 28, 720p) + Supabase camera_clips insert + behavior_logs(source='human') 자동 GT 라벨.
- **macOS APFS NFD 함정**: 한글 파일명이 NFD(분리형)로 저장됨 → Python 리터럴 NFC와 매칭 실패 9/16. `unicodedata.normalize("NFC", stem)` 적용으로 해결.
- 첫 시도에서 7건 중복 생성 → cleanup 스크립트로 `has_motion=false` 처리(비파괴, 파일·GT 보존).
- 결과: 16 active + 7 excluded. GT 분포: eating_prey 7, shedding 4, defecating 3, eating_paste 2.

#### Phase 3: 89건 baseline 정밀화 (부분 완료)
- conf<0.5 신호 무용화 — 89건 중 1건뿐(GT=unseen 정답). 모델은 틀려도 conf 0.8~0.95.
- disagreement 25건 추출 (정확도 71.6%) → hot pattern: `GT=moving → pred=eating_paste` 12건 (confabulation).
- 사용자 검수 리스트 `/tmp/phase3-review-list.md` 작성. 검수 결과 따라 향후 정확도 재계산 가능 (블로킹 없음).

#### Phase 4: v3.4 zero-shot 105건
| 항목 | 값 |
|---|---|
| 전체 정확도 | **79/105 = 75.2%** |
| 새 16건 | 13/16 = 81.2% |
| 기존 89건 | 66/89 = 74.2% (v3.3 71.6% +2.6%p — shedding 추가가 회귀 안 일으킴, 오히려 ↑) |
| **shedding 회수** | **4/4 = 100%** (prompt 추가만으로 완벽 인식) |
| shedding new-flag | 3건 (GT=moving → pred=shedding) — 검수 후보 (v3.3엔 옵션 없어서 moving으로 라벨됐을 가능성) |

**클래스별:** eating_paste 91% / eating_prey 73% / drinking 55% / defecating 50% / shedding 100% / hiding 0% / moving 81% / unseen 100%.
- ⚠️ **hiding 0% (0/4)** — 4건 모두 moving으로. 큰 회귀, prompt tune 후보.
- ⚠️ **drinking 55%** — 5건 중 4건 eating_paste 환각. confabulation 잔존.

#### Phase 5: v3.4 4-shot 99건 (FAIL 2 + examples 4 빠짐)
| 항목 | 값 |
|---|---|
| 4-shot 정확도 | 70/99 = **70.7%** |
| zero-shot (동일 99건) | 75/99 = **75.8%** |
| **Δ** | **-5.1%p (퇴행)** |

**5-카테고리:** held-correct 63 / recovered 7 / **broken 12** / still-wrong 17 / missing 2.

#### Phase 6 결정: **0-shot 운영 유지**

| 기준 | 임계값 | 측정값 | 충족 |
|---|---|---|---|
| 4-shot − 0-shot | > +3%p | -5.1%p | ❌ |
| recovered > broken | recovered 7 > broken 12 | broken 우세 | ❌ |

→ **4-shot 채택 보류**. 비용 5배 + 시간 6배 (30분 → 3시간) 들여서 정확도 손실.

#### v3.4 핵심 통찰 — "Better prompt obviates few-shot"
1. **Zero-shot baseline 자체가 강해지면 examples의 marginal advantage가 사라짐.** v3.3 zero-shot 71.6% → v3.4 zero-shot 74.2% (+2.6%p in 89건 동일). v3.4 prompt(rule 8/9 추가)가 confabulation 억제를 잘 함 → examples은 오히려 noise.
2. **broken 12건 패턴**: 9건이 `moving → eating_paste`. examples 구성 (eating_paste positive 2 + moving 2)이 eating_paste prior를 강화시키는 부작용. v3.3에선 이 강화가 도움됐지만 v3.4에선 prompt 자체로 prior가 적정 → examples이 오버드라이브.
3. **v3.3 vs v3.4 4-shot 효과 반전**: v3.3 환경 +3.9%p → v3.4 환경 -5.1%p. **same examples, different system prompt → opposite effect**. 단순 "few-shot이 좋다/나쁘다"가 아니라 prompt-examples 정합성이 핵심.
4. **shedding은 prompt 추가만으로 100% 회수** — 새 클래스 도입은 examples 없이 prompt 정의만으로 충분. 데이터 수집 비용 절감.

#### 잔존 약점 (다음 라운드 후보)
- **hiding 0%**: 4건 모두 moving으로. 클립 일부만 hiding이라 단일 라벨 한계 + prompt 정의 모호. 클립 분할 라벨 도입 또는 hiding 정의 강화 검토.
- **drinking 55%**: 4건 eating_paste 환각. 투명/불투명 disambiguation rule 8이 모든 케이스를 못 잡음. 야간 IR 그레이스케일 영상에서 투명도 신호 약화 가능성.
- **defecating 50%**: 데이터 4건뿐. 통계 의미 약함, 데이터 보강 필요.

#### 재현 자료
- 추론 스크립트: `/tmp/infer-v34-zeroshot.py`, `/tmp/infer-v34-fewshot.py`.
- 결과 JSONL: `/tmp/v3.4-zeroshot.jsonl`, `/tmp/v3.4-fewshot.jsonl`.
- import 스크립트: `/tmp/import-inbox-0429.py`, `/tmp/cleanup-duplicates.py`.
- 검수 리스트: `/tmp/phase3-review-list.md`.

### 3-9. Round 2 진입 (v3.5, 2026-04-30)

**트리거**: Round 1 3차 평가 후 사용자 면담에서 **"75.2%면 서비스 못 한다"** 우려 제기. 클래스별 분포·시각 정보 한계·데이터 수집 메커니즘을 root cause 차원에서 재진단 → **클래스 재설계 + HITL 도입** 결정.

**SOT 결정 17~20 반영** (`tera-ai-product-master/docs/specs/petcam-poc-vlm.md` §결정사항 참조):

| 결정 | 구현 영향 |
|------|----------|
| #17 drinking/eating_paste raw 유지 + UI는 `feeding` 통합 | DB 스키마 변경 없음. API/UI 레이어에서 통합 표시 — Phase 1 진입 시 구현 |
| #18 hiding 클래스 폐기 (8 클래스) | `prompts/system_base.md` decision rule 4(partial occlusion-hiding) 제거, priority에서 hiding 제거 / `prompts/species/crested_gecko.md` available_classes에서 `hiding` 제거 — **완료** |
| #19 eating_prey stalking 정의 명시 | `prompts/system_base.md` rule 7 추가, `crested_gecko.md` eating_prey 정의 보강 — **완료** |
| #20 HITL 도입 (앱 사이드) | Phase 1 펫캠 앱 구현 시 라벨 컨펌 UI. PoC 본 스펙 범위 외 |

**v3.5 prompt 변경 검증** (`/tmp/infer-v35-zeroshot.py` 시작 시 자동 체크):
- `shedding` 키워드 포함 ✓
- `stalking` 키워드 포함 ✓
- `- hiding:` 클래스 정의 미포함 ✓

**평가 시 GT 매핑**: human GT가 `hiding`인 4건은 평가 시 `moving`으로 변환 (raw DB는 보존).

**Root cause 진단 (non-moving GT 오답 15건)**:

| 카테고리 | 케이스 | 진단 |
|---------|-------|------|
| A. drinking ↔ eating_paste 시각 한계 | 4건 (conf 0.9~0.95) | 영상 픽셀에 투명/불투명 신호 부족 — prompt로 못 풀음 |
| B. hiding 미인식 | 4건 | 모션 트리거 충돌 — 폐기 결정 |
| C. eating_prey stalking 정의 불일치 | 3건 | rule 7 추가로 해결 시도 |
| D. defecating 시각 패턴 미학습 | 2건 | 데이터 4건 통계 무의미 |
| E. 보수 미스 | 1건 | 정상 |
| F. **모델 한계 의심** (`ff1ecb03`) | 1건 | drinking 4회 추론 모두 못 봄. **Pro/Sonnet 측정 필요** |

**핵심 인사이트**: 105건 중 98%가 conf ≥0.8인데 정확도 75.7%. **confidence-based abstain 불가** — HITL이 정공법.

**Round 2 액션 우선순위**:
1. ~~v3.5 zero-shot **107건** 재추론~~ — **완료 (2026-04-30)**, 결과는 §3-10
2. ~~Gemini Pro cherry-pick 8건 측정~~ — **완료 (2026-04-30)**, 결과는 §3-11
3. Claude Sonnet 4.6 측정 — `ANTHROPIC_API_KEY` 확보 후 진행 (cherry-pick 동일 8건)
4. 작은 클래스 데이터 보강 (drinking/defecating/eating_prey 각 20~30건) — HITL 굴러가면 자연 누적
5. HITL UI 구현 (Phase 1)

#### 재현 자료 (v3.5)
- 추론 스크립트: `/tmp/infer-v35-zeroshot.py` (모델 ID `gemini-2.5-flash-zeroshot-v3.5`)
- 결과 JSONL: `/tmp/v3.5-zeroshot.jsonl` (107건 OK, 0 FAIL, 1756s)
- non-moving 오답 분석 결과: `/tmp/non-moving-wrong.json`

### 3-10. Round 2 v3.5 zero-shot 평가 결과 (2026-04-30)

| 항목 | 값 |
|---|---|
| 전체 정확도 | **87/107 = 81.3%** |
| v3.4 동일 105건 재계산 | 83/107 = 77.6% (어제 GT 정정 4건 반영 후) |
| **Δ vs v3.4** | **+3.7%p** |
| 추론 시간 | 1756s (29분, avg 16.4s/clip) |
| 비용 (Flash 기준) | ~$0.20 추정 |

**5-카테고리:**
- held-correct 77 / **recovered 8** / **broken 6** / still-wrong 14 / missing 2 (둘 다 정답)
- Net: **+4건** (recovered 8 - broken 6 + missing 2)

**클래스별 정확도 (v3.5):** shedding 100% (4/4) / eating_paste **92%** (12/13, v3.4 91% 유지) / eating_prey **90%** (9/10, v3.4 73% → ↑↑) / unseen 100% / moving 80% / defecating 75% / drinking **60%** (6/10, 시각 한계 미해결).

**recovered 8건 패턴:**
- `moving → eating_paste` 오인 회복 4건 (rule 1/9 강화 효과)
- `hiding → moving` 자동 매핑 2건 (결정 #18 검증)
- `eating_prey stalking` 회복 1건 (rule 7 효과, `d70cebe1`)
- `moving → shedding` 오답 회복 1건

**broken 6건 패턴:**
- `moving → eating_paste` **5건** ← rule 9(shedding vs eating) 추가가 eating_paste 정의를 over-trigger 시킨 부작용 의심
- `eating_paste → moving` 1건

**핵심 잔존 이슈:**
- **moving → eating_paste 오답 11건** (broken 5 + still-wrong 6) — 시스템 패턴
- **drinking 60%** (4건 오답: drinking→eating_paste 2 + drinking→moving 2) — 시각 한계, prompt로 못 풀음 가능성 高 → **#2 Pro/Sonnet 모델 한계 검증 필요**

**결정**: v3.5 채택 (+3.7%p). 잔존 약점은 모델 한계 vs prompt 한계 분리 후 추가 액션 결정.

#### 재현 자료 (v3.5 결과)
- 추론 결과: `/tmp/v3.5-zeroshot.jsonl` (107건 OK)
- 추론 로그: `/tmp/v3.5-infer.log`

### 3-12. v3.5 zero-shot 159건 (inbox/0430 +52) + feeding 통합 (2026-04-30)

inbox/0430 52건 추가 import (drinking 1 / eating_prey 8 / eating_paste 4 / defecating 12 / shedding 25 / moving 2). 파일명 = GT 자동라벨, 예외 2건(`병_신드롬 1`, `행동_싫어하는 소리 1`)은 moving + 원제목 notes 보존.

**feeding 통합 정의 (Round 2 결정 #17 정공법):** `drinking ≡ eating_paste ≡ feeding`. **raw 라벨은 DB/prompt 그대로 보존**, 평가/UX 레이어에서만 묶음.

| 항목 | 값 |
|---|---|
| 전체 정확도 (raw) | 130/159 = **81.8%** |
| + hiding→moving 매핑 | 133/159 = 83.6% |
| **+ feeding 통합** | **136/159 = 85.5%** |
| 신규 52건 (raw) | 45/52 = 86.5% |
| 신규 52건 (feeding) | 46/52 = 88.5% |

**v3.4 vs v3.5 5-카테고리 (overlap 105건):**
- held-correct 78 / **recovered 8** / **broken 4** / still-wrong 15
- missing 54 (v3.4 미실행 신규 + 어제 보충): 정답 47/54 = 87.0%
- **recovered > broken (8 > 4)** — 더 깨끗 (107건 8/6 대비)

**클래스별 정확도 (raw / feeding 통합):**
| class | n | raw | feeding |
|---|---|---|---|
| moving | 64 | 83% | 83% |
| shedding | 29 | **97%** | 97% |
| eating_prey | 19 | 84% | 84% |
| eating_paste | 17 | **100%** | 100% |
| defecating | 16 | 69% | 69% |
| drinking | 12 | 50% | **83%** (+4) |
| unseen | 2 | 100% | 100% |

**feeding 합쳐 본 정확도**: drinking + eating_paste GT 29건 → feeding 예측 **27/29 = 93.1%**. 새는 2건:
- `987c7b5d` GT=drinking → moving ("벽면 핥음, paste 안 보임")
- `ff1ecb03` GT=drinking → moving (어제 cherry-pick에서 Pro도 못 풀음, 시각 한계 확정)

**잔존 오답 Top:**
- `moving → eating_paste` **9건** ← rule 9 over-trigger 잔존 (cherry-pick 가설 재확인, 159건 모수에서도 동일)
- `drinking → eating_paste` 4건 (feeding 통합 시 자동 해결)
- `defecating → moving` 4건 (n=4 → 16으로 늘면서 새로 노출)
- `eating_prey → moving` 3건
- `moving → shedding` 2건

**핵심 인사이트:**
1. **feeding 통합 효과 입증** — raw 81.8% → 85.5% (+3.7%p). drinking 50% (시각 한계)을 UX 레이어로 우회.
2. **shedding 97% (n=4 → 29, 7배)** — 신규 데이터 일반화 양호. 클래스 정착.
3. **eating_paste 100% (n=17)** — 자율피딩 시각 패턴 robust.
4. **moving → eating_paste 9건 over-trigger**가 최대 잔존 — Round 3 rule 9 약화 후보.
5. **defecating 69%** — n 늘면서 새 실패 패턴 노출. 라벨 검수 + prompt 점검 라운드 3.

#### 재현 자료
- 추론 결과: `/tmp/v3.5-zeroshot.jsonl` (159건 OK, 0 FAIL)
- 분석 스크립트: `/tmp/analyze-v35-full.py` (feeding/hiding 매핑 포함)
- import 스크립트: `/tmp/import-inbox-0430.py`

### 3-11. Pro cherry-pick 8건 검증 (2026-04-30)

Round 2 액션 #2 — drinking 시각 한계와 moving→eating_paste over-trigger가 **Flash 한계인지 모델 공통 한계인지** 분리 검증.

**대상 8건** (v3.5 zero-shot 오답 중 두 패턴):
- A. drinking 4건 (`05da625c`, `2420abd8`, `b61ef5ea`, `ff1ecb03`) — 시각 정보 한계 가설
- B. moving→eating_paste 4건 (`09bc2ee4`, `65b57205`, `76a24e8b`, `379e97a3`) — rule 9 over-trigger 가설

**조건**: 동일 v3.5 system prompt + crested_gecko prompt, `gemini-2.5-pro`, `temperature=0.1, top_p=0.95, response_mime_type=application/json`. 추론 시간 114s (avg 14.2s/clip), 비용 ~$0.10 추정.

| prefix | GT | Flash v3.5 | Pro v3.5 | F-conf | P-conf | Verdict |
|---|---|---|---|---|---|---|
| 05da625c | drinking | eating_paste | moving | 0.95 | 0.90 | BOTH-WRONG |
| 2420abd8 | drinking | eating_paste | **drinking** | 0.90 | 1.00 | **PRO-ONLY ✓** |
| b61ef5ea | drinking | moving | moving | 0.90 | 1.00 | BOTH-WRONG |
| ff1ecb03 | drinking | moving | moving | 0.80 | 1.00 | BOTH-WRONG |
| 09bc2ee4 | moving | eating_paste | **moving** | 0.90 | 0.90 | **PRO-ONLY ✓** |
| 65b57205 | moving | eating_paste | eating_paste | 0.95 | 1.00 | BOTH-WRONG |
| 76a24e8b | moving | eating_paste | eating_paste | 0.90 | 1.00 | BOTH-WRONG |
| 379e97a3 | moving | eating_paste | eating_paste | 0.95 | 1.00 | BOTH-WRONG |

**총 정확도**: Flash 0/8 (0%) → Pro 2/8 (25%). 모델 1단계 업그레이드로도 6/8은 여전히 틀림.

**가설 검증 결과**:
- **A. drinking 시각 한계** → 부분 검증. Pro도 4건 중 1건만 정답. **3건은 모델 차이도 같은 답(또는 다른 오답)** → 픽셀에 정답 신호 부족 가설 강화. memory `feedback_vlm_visual_information_limit.md` 정공법: UX 통합 / 메타데이터 / HITL.
- **B. moving→eating_paste over-trigger** → 강하게 검증. Pro도 4건 중 3건이 동일하게 eating_paste로 over-call. **rule 9 (shedding vs eating disambiguation)이 prompt 단에서 eating_paste 정의를 부풀려놓은 게 모델 공통으로 작동**. Flash 단독 문제 아님 → **prompt 손보기**가 정공법.

**Pro의 confidence 패턴 주의**:
- Pro 7/8 케이스가 conf 1.00. **확신에 찬 오답** = confabulation 신호. confidence-based abstain은 Flash뿐 아니라 Pro에서도 무력 (memory `feedback_vlm_confidence_abstain_limit.md` 재확인).

**결정**:
- Pro 단독 채택 ROI 없음 (정확도 +25%p이지만 단가/속도 ~10x). **운영은 Flash 유지**.
- A 그룹: drinking 클래스는 prompt/모델로 더 못 풂 → **UX 통합 (drinking + eating_paste → "feeding" 묶기)** 검토.
- B 그룹: rule 9 over-trigger 패턴 → 다음 라운드에서 **eating_paste 트리거 조건 좁히기 + rule 9 약화** 실험.
- Sonnet 4.6 검증은 ANTHROPIC_API_KEY 확보 후 동일 8건으로.

#### 재현 자료 (Pro)
- 추론 스크립트: `/tmp/cherrypick-pro.py` (모델 ID `gemini-2.5-pro-zeroshot-v3.5`)
- 결과 JSONL: `/tmp/cherrypick-pro.jsonl` (8건 OK, 0 FAIL, 114s)
- 비교 스크립트: `/tmp/cherrypick-compare.py`

### 3-13. Round 3 — baseline 깨기 시도 3회 모두 실패 (2026-04-30)

v3.5 85.5% 잔존 오답(특히 `moving → eating_paste` 9건)을 prompt로 풀어보려 했으나, 3가지 방향 모두 v3.5 baseline 대비 퇴행. **잔존 오답은 prompt 한계가 아닌 시각 한계**로 결론.

| 시도 | 방향 | prompt 변경 | 결과 (feeding-merged) | 5-카테고리 |
|---|---|---|---|---|
| **v3.6** | rule 강화 + duration 메타 prior | tongue 룰 강화 + `WEAK PRIOR: long clips ≥ 30s lean moving` | **84.3%** (-1.9%p) | recovered 5 / broken 10 |
| **v3.7-B** | rule 약화 (6 spots) | rule 1·2 + species 4곳 약화 | **81.1%** (-5.0%p) | recovered 4 / broken 12 |
| **v4** | clean slate (legacy 무시) | 1641 chars, 6 클래스 (drinking+eating_paste→feeding 통합), 룰 0 | **79.2%** (-6.9%p) | recovered 4 / broken 15 |

**채택 가드 (Δ > +2%p AND recovered > broken)**: 3개 모두 ❌.

**공통 메커니즘**:
1. **v3.5 patch들은 false positive 방어 역할** — "tongue tip MUST contact food" 같은 강제 룰이 inspecting을 eating으로 부풀리는 걸 막음. v3.7-B/v4에서 룰 제거하니 모델 default가 "음식 근처면 feeding"으로 흘러감 (v4 confusion: GT=moving 64건 중 16건이 feeding으로 false positive).
2. **vague prompt = false positive 폭발** — clean slate 단순함은 매력적이나 boundary가 흐려져 specific 클래스 방향으로 흐름. 6 클래스 축소도 prompt 레벨에선 효과 없음 (평가 레이어 매핑과는 다른 메커니즘).
3. **donts/vlm.md 룰 5와 동형** — 강한/약한 시그널 무관하게 prompt 변경 자체가 모델 attention을 흔듦.

**결론 — v3.5 85.5% production 확정**:
- 추가 prompt 변경 stop. 비용 대비 ROI 0.
- 잔존 오답(특히 `moving → eating_paste` 9건, drinking 시각 한계 4건)은 **다른 layer로**:
  - **UX 통합** — drinking + eating_paste → "feeding" 묶음 (이미 평가 레이어 93.1% 검증, prompt 미반영 정공법)
  - **메타데이터 보강** — dish detection / before-after behavior로 시각 단서 보충
  - **HITL** — 저신뢰 케이스 운영자 검수 큐
- prompt 백업: `web/prompts/backups/system_base.v3.5.md`, `crested_gecko.v3.5.md`

#### 재현 자료
- 추론 스크립트: `/tmp/infer-v3.6-zeroshot.py`, `/tmp/infer-v37b-zeroshot.py`, `/tmp/infer-v4-clean.py`
- 결과 JSONL: `/tmp/v3.6-zeroshot.jsonl`, `/tmp/v3.7b-zeroshot.jsonl`, `/tmp/v4-clean-zeroshot.jsonl` (각 159건)
- 분석 스크립트: `/tmp/analyze-v36-vs-v35.py`, `/tmp/analyze-v37b-vs-v35.py`, `/tmp/analyze-v4-vs-v35.py`
- 메모리: `feedback_vlm_rule_overcorrection.md` (3 시도 + 공통 메커니즘 + How to apply)

### 3-14. Round 3 후속 — multi-track ablation + post-filter 폐기 + UX 통합 적용 (2026-05-01~02)

§3-13 직후, prompt가 아닌 **다른 layer**로 잔존 오답을 풀어보려 두 갈래 시도. 결국 **시각 한계 확정 + UX 통합 정공법 도입**.

**(a) Multi-track ablation — 잔존 오답 26건 × 5트랙 (2026-05-02)**

prompt 변경이 정말 ROI 0인지, 한 번 더 확인할 겸 잔존 오답 26건만 골라 5 트랙 동시 추론 (130 inference, 22분, $1).

| Track | 가설 | recovered | broken | 순효과 |
|---|---|---|---|---|
| A (baseline) | v3.5 그대로 | — | — | 8/26 정답 |
| B (position-first) | 그릇/물 위치 먼저 식별 | 1 | 5 | -4건 |
| C (tongue-target) | 4지선다 paste/water/other/none | 0 | 5 | -5건 |
| D (chain-of-thought) | 5-step reasoning | 4 | 4 | swap (0) |
| E (conservative-default) | 기본값 moving | 1 | 2 | -1건 |

→ **어느 트랙도 baseline 못 넘음**. G1(그릇 머무름→eating환각) ceiling 5/10. B/C는 eating_paste 환각을 오히려 강화 (15/26 vs A 7/26). 메모리 `feedback_vlm_error_set_ablation_pattern.md`에 진단 방법론 박음.

**(b) dish-presence post-filter — 폐기 (2026-05-01~02)**

raw {drinking, eating_paste}에 Flash binary 라우터(`dish_present`+`licking_behavior`) 호출 → 5룰 후처리 → 154건 final accuracy 측정.

| 메트릭 | 수치 |
|---|---|
| 154건 final | **84.42%** (130/154) |
| v3.5 floor (154 기준) | 85.7% (132/154) |
| Δ | **-1.3%p (FAIL)** |
| broken / recovered / still-wrong | 0 / 2 / 24 |

→ **binary 라우터도 prompt 레이어** (같은 시각 정보·같은 모델). spec [`feature-vlm-feeding-postfilter.md`](feature-vlm-feeding-postfilter.md) 🗑️ 폐기. 메모리 `project_vlm_dish_postfilter_attempt.md`.

**(c) 결론 — 6번째 검증 누적 → UX 통합 정공법 채택**

v3.6/v3.7-B/v4 + Track B/C/D/E + dish-postfilter = **6 시도 모두 baseline 못 넘음**. 잔존 오답은 prompt/router로 안 풀리는 **시각 한계** 확정. floor 갱신: 159건 85.5% AND 154건 85.7% (둘 다 의무).

**(d) UX 통합 적용 — 본 라운드 첫 layer 정공법**

평가 레이어에서 이미 93.1% 검증된 매핑(`drinking + eating_paste → feeding`)을 **UI까지 일관 노출**. raw 9는 DB·human label 입력에 그대로 보존.

- `web/src/types.ts` — `toFeedingMerged()` + `UI_BEHAVIOR_CLASSES` 8 readonly tuple export.
- F3 결과 비교 (`results/page.tsx` + `PairTable.tsx`) — `match` 판정 매핑 후, Confusion Matrix 8클래스, Pair Badge 매핑 후 (`title=` 속성에 raw 보존).
- 평가 매핑 동치 가드 — `web/eval/v35/check-feeding-merge.py` 9 케이스 단언 (TS ↔ Python `FEEDING_MERGE` 미러). 매핑 정의 측 명시 주석.
- 클립 피드 필터는 out 처리 (해당 화면 자체 부재 — 별도 spec 가치).

연관 spec: [`feature-vlm-feeding-merge-ux.md`](feature-vlm-feeding-merge-ux.md) ✅, [`feature-vlm-hitl-ping.md`](feature-vlm-hitl-ping.md) 🚧 (G2/G4/G5 모호 케이스 보강용).

#### 재현 자료
- 추론/분석 스크립트: `web/eval/v35/{infer-multi-track.py, analyze-multi-track.py, infer-dish-presence.py, postfilter.py, analyze-postfilter.py, check-feeding-merge.py}`
- 결과 JSONL: `web/eval/v35/{error-set-154.jsonl, multi-track-zeroshot.jsonl, dish-zeroshot.jsonl, dish-presence-gt.jsonl}`
- 메모리: `feedback_vlm_rule_overcorrection.md` (6 시도 표) / `project_vlm_dish_postfilter_attempt.md` / `feedback_vlm_error_set_ablation_pattern.md` / `project_vlm_v35_baseline_lock.md` (154건 floor 추가)

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
