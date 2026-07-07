# 다음 세션 시작 지점

> 매 세션 마지막에 갱신. 다음 세션 초입에 먼저 읽는다.
> **최종 갱신:** 2026-07-07 (3) — **라벨링 웹 단일 통합 + night worker 로그인 복구(claude 재로그인 + classify is_error 안전망) + gate 검증 reject.** night worker "행동 빔" 원인 = claude 로그인 풀림(한도 아님, classify가 "Not logged in"을 rc=0로 받아 unseen 조용히 삼킴). gate RF-DETR v2 = recall 90.9%<95%(게코 9% 완전검출실패, threshold도 천장)→v3 재학습 대기. 자동화 = 활동 프로파일(claude 0)만, 행동(gate) 보류. 상세 ↓ 07-07(3) 블록.
> **(이전 갱신)** 2026-07-07 (2) — **과거 백로그 백필 파이프라인 구축 + 릴리화이트+아잔틱 모프 shedding 오판 규명.** 자동화 사각지대(과거 3일)를 `backfill_window`(nightly, 분석+jsonl 멱등재개)→`register_motion_candidates`(lab, motion_clips→camera_clips 미러+vlm후보)로 처리. 토밤 카메라B 71전수→비-moving 8후보 편입→**owner 육안 8/8 moving**(claude shedding7·drinking1 전부 오답). shedding 오판 정체=**릴리화이트+아잔틱 모프 흰무늬**(IR서 허물로 환각)→이 개체 shedding 상시오탐, 리포트 탈피시그널 신뢰도0. 팔로업=classify temperature 비결정성. 메모리 3개 신설. 상세 ↓ 07-07(2) 블록.
> **(이전 갱신)** 2026-07-07 — **nightly 윈도우 워커 MVP-0 구현 + 맥미니 배포 완료.** W0~W5 전부(nightly 커밋 8개 push)+맥미니 launchd 등록·야간 **22/00/02/04시** 자동·**1박 실측 개시**(00시 첫 카드 `exit 0`, claude 5회 성공, Slack 카드). **핵심 재설계**: W3 스파이크 clip당 **~12만 토큰** 발견→원안'전량 claude'(한도초과)를 **뼈대=DB(활동량/시간대, claude 0회)+행동=top-N 샘플 claude**로 분리. 다음=아침 실측확인(claude 한도소모·본인작업 지장)→`SAMPLE_TOP_N`/스케줄 튜닝. 상세 ↓ 07-06 블록.
> **(이전 갱신)** 2026-07-02 — **북극성(먼 미래 최종목표) 확정.** 양서파충류 행동분석 AI(이상감지는 응용), 데이터로 '아는' 회사. 연구시장 작아 **동물병원(B2C WTP)+무인호텔링(유통노드)**로 고객 피벗. `docs/petcam-north-star.md`+메모리 `north-star-vision`. **다음 세션 3트랙**: ①미세행동 완벽분류(⚠️비-VLM 경로) ②gate 카메라 가동 ③mac mini 자동화(claude 한도분리 선행). 상세 ↓ 07-02 블록.
> **(이전 갱신)** 2026-06-20(2) — **맥미니 워커 Phase 0 완전 종료.** 맥미니 본체 clone→launchd→**재부팅 생존 검증 ✅**(23:01). launchd PATH 버그(uv≠claude bin) 수정·push(`c3f04e2`). FileVault off + 자동로그인. **claude 구독 한도 공유 문제 발견**(워커 5분폴링 288회/일 + 본인작업이 같은 한도→초과, Phase1 한도분리 필수). 검증 끝나 스모크 bootout. 상세 ↓ 06-20(2) 블록.
> **(이전 갱신)** 2026-06-20 — 맥미니 워커 Phase 0 스모크 **맥북** 검증(6/6) + cron→launchd 발견 + GitHub push. ↓ 06-20 블록.
> **(이전 갱신)** 2026-06-18 — **펌웨어 R2 계약 + dataset 송부 v4.0 + DB sync 유령 정리.** nightly indexer=B방식(camera_clips.started_at BETWEEN 쿼리, object store는 시간조회 약함→DB가 시간 인덱스) 확정 → **펌웨어 R2 clip 등록 계약 핸드오프**(`docs/handoff-prompts/camera-firmware-clip-contract.md`, started_at=녹화 시작 UTC, ESP32-P4 서버경유 DB-last, **계약 v1 확정**(terra 별도 Supabase `motion_clips`, 리포터 옵션1 직접조회)) + **dataset-203 전문가 송부 v4.0 갱신**(README 전면재작성·`prompt_v4.0.md` 신규·analyze.py 적응형+7class, storage gitignore→zip 송부) + **DB GT sync 4건 유령 정리**(실측=06-12 이미완료). 메모리 3개 신설(object-store-time-index·run-sot-function-reconstruct·recalled-memory-verify). 상세 ↓ 06-18 블록. (이전: 06-17 RBA 파이프라인 통합 설계)

## 🆕 2026-07-07 (3) — 라벨링 웹 통합 + night worker 로그인 복구 + gate 검증(reject)

**완료:**
- **라벨링 웹 단일 통합** (수정1): `/`(옛 Gemini PoC 대시보드)와 `/labeling`(현행 큐)이 따로 보이던 것 → `/`→`/labeling` redirect + 옛 PoC 화면(queue·inference·results·upload·clips + api·lib·컴포넌트) 삭제. 관리자 전용. 커밋 `aff27a4`(tsc 통과, 죽은 링크 0).
- **night worker "행동 빔" 원인 규명 + 복구** (수정2): 증상=리포트는 오는데 케어시그널 항상 빔. 원인=**claude 로그인 풀림**(한도 아님!). worker 정상(runs=3), classify가 claude의 "Not logged in"(rc=0+envelope.is_error)을 `_parse`서 **unseen 으로 조용히 삼킴**→로그 0바이트. **맥미니 재로그인으로 즉시 복구**(PING_OK, backfill 300 api_error 0). + `classify.py` **is_error 안전망**(rc=0이어도 envelope.is_error→action=error+`[classify] api_error` 로그) nightly 커밋 `3d66bcb`.
- **gate detector 검증 = reject** (`experiments/gate-recall/` TEST-SHEET+REPORT): RF-DETR gecko_v2를 backlog 300(claude 프록시GT)로. **recall 90.9%<95%**(claude 게코있음 220 중 20개를 detector 검출 score=0로 완전 놓침, threshold 0.1~0.6 sweep 전부 recall 천장 90.9%) · specificity 40%(unseen 80중 32만 걸름). 스모크 bbox 고정오탐 우려는 해소(전수 223 unique). **현 detector로 gate 못 씀** → 활동 프로파일(claude 0)만 자동화, 행동(gate)은 v3 후.
- **캡처 vs 분석비용 전략** (`docs/AI-VIDEO-ANALYSIS-STRATEGY.md §6.6`, 커밋 `a04ac7b`): motion_score론 노이즈 vs 미세 케어행동(혀만 움직이는 음수/급여, score≈0) 구분 불가 → 임계값↑=미세행동 손실. **캡처는 민감 유지, 분석단계 gate로 unseen 필터**("크기"아니라 "게코 존재/위치"로). 메모리 `capture-sensitivity-gate-cost`. + gate "상시가동" 오기록 정정(실측 맥미니 미배포).
- **backfill 배치·재개 확장**: `backfill_window.py`에 --camera ALL·--sort started_at·--night-only(20~06시)·error 미기록 재시도·12h조각(limit 회피) 추가. 07-03밤 300개(20~02시) **완주(api_error 0=밤당 300 한도 클린)** — 게코 73%·unseen 27%·전부 moving(shedding 2는 모프 오탐). 301~600 nohup 진행 중(맥미니 PID 26965, 07-04 02:25부터).

**팔로업 (우선순위):**
1. ⭐ **오늘밤 worker 자동 실행 관찰** — 로그인 복구 + is_error 안전망 후, 22/00/02/04시 정상 리포트(활동+행동 top-N) 오나. 문제 시 맥미니 `grep "\[classify\]" /tmp/nightly-reporter.log`.
2. **301~600 완주 + backlog 601~ 나머지** — 맥미니 진행 중. 전수 계속 시 하루 300개(claude 한도 리셋 1:10am)씩 며칠. 재개: `backfill_window.py --camera ALL --sort started_at --night-only --start ...T20:00+09 --end ...T06:00+09 --top-n 300 --out storage/backfill/backlog.jsonl`(done skip 자동).
3. **gate v3 재학습** — 불일치 68개(FN 20=게코인데 검출0 + FP 48=unseen인데 visible) **육안→사람 GT**(FP 중 "detector 맞고 claude 놓침" 비율이 관건)→재학습(gecko_v3)→같은 시험지 재검증. 300 clip=`/tmp/gate_clips`(또는 `scripts/_gate_download_all.py` 재다운). detector 레포=`~/myPythonProjects/gecko-vision-gate` runs/gecko_v2.
4. **활동 프로파일 자동화 최적화** — worker를 활동-only(행동 top-N 빼거나 gate 후로). 지금은 활동+top-N 다 나옴(top-N은 moving 편향).

**임시 스크립트:** `scripts/_gate_download_all.py`(커밋, v3 재검증 재사용) · `_gate_smoke_download.py`·`_delete_clip.py`(로컬 미커밋).

---

## 🆕 2026-07-07 (2) — 과거 백로그 백필 파이프라인 + 모프 shedding 오판 규명

**완료 (백필 파이프라인 자산화 + owner GT 확정):**
- **배경**: launchd 워커는 "직전 윈도우"만 처리 → 자동화 착수 전 쌓인 과거 3일(금~일, `motion_clips` 1609clip) 사각지대. 수동 백필 필요.
- **활동 프로파일**(claude 0회, DB집계): 야행성 이중봉(새벽 1~5시 정점 + 저녁 20~22시). 카메라 대비 = B(f659)=밤만 깨끗한 야행성 / A(5b3e)=낮에도 모션(오탐 or 다른 개체).
- **핵심 발견 — "활발 top-N = moving 편향"**: motion_score 상위만 뽑으면 큰 움직임=이동만 걸림. 정적 행동(음수/급여)은 score 낮아 누락. 토밤 top10 전부 moving, 전수 71에서야 score 낮은 것 섞여 drinking/shedding 후보 출현 → 샘플은 "골고루"(시간대·score 분산) 필요. (nightly `SAMPLE_TOP_N` 튜닝 근거)
- **백필 실행**: 토밤 카메라B 71 전수 claude(v4.0 sonnet) → 비-moving 8후보(shedding7+drinking1) camera_clips 미러+behavior_logs(vlm) 편입. **owner 육안 8/8 moving 확정** — claude 비-moving 판정 전부 오답. (moving 56·unseen 7은 분석만, 미편입)
- **⭐ shedding 오판 정체 = 릴리화이트+아잔틱 모프**: owner "오늘 탈피0" 확정. shedding 근거 "창백/주름진 희백색"이 허물 아니라 이 개체 모프 무늬(IR서 환각 심화) → nightly Sonnet이 이 게코 shedding 상시오탐, 리포트 탈피시그널 신뢰도0. (메모리 `gecko-morph-shedding-false-positive`)
- **자산**: `backfill_window.py`(nightly, --out jsonl 멱등재개) + `register_motion_candidates.py`(lab). DB이원화 규명(`motion_clips` 실운영 vs `camera_clips` 라벨링/평가 완전분리, 미러 필수, `source` CHECK=camera/upload/youtube 함정). 라벨링 큐=camera_clips+본인 behavior_labels 없는 것, owner 계정 로그인 필요. 개별 URL=`label.tera-ai.uk/labeling/{clip_id}`.

**팔로업:**
1. ⭐ **classify temperature 비결정성** — claude -p temperature 미설정→같은 클립 라벨 흔들림(top10 drinking→전수 moving). nightly `classify.py` 수정(claude CLI temperature 지원 확인). (메모리 `nightly-classify-nondeterministic-temperature`)
2. **이 게코 shedding 억제** — 모프 반영 프롬프트/후처리 or HITL 별도검증. 리포트 케어시그널 신뢰도 직결.
3. **백필 잔여** — 71중 8개만 GT. moving 56·unseen 7은 claude 후보만(전수 GT 원하면 추가). 카메라A·타 날짜 미처리.

**상세:** 메모리 3개 · `scripts/register_motion_candidates.py`(lab) · `~/petcam-nightly-reporter/scripts/backfill_window.py`

---

## 🆕 2026-07-06 — petcam 자동화 착수 결정 (nightly 윈도우 워커 계획서)

**대화로 결정 (코드 0 — 계획서만, 커밋 대기):**
- **자동화 첫 타겟 = nightly 아침 리포트** (사용자 선택 — gate/한도분리보다 "눈에 보이는 산출물" 우선). 실측: 카메라 2대(ESP32-P4 dev, owner e2d0a451) `motion_clips`에 활발히 유입(7/4 **802건**, 총 2500+, 밤 폭증=야행성). `camera_clips`는 레거시(06-17 이후 0). `clip_prelabels` 테이블 아직 없음(gate 로컬만). gate는 claude 안 씀(RF-DETR)이라 블로커 0.
- **claude 한도 = 구독 그대로 1박 실측 후 분리 결정** (조기최적화 회피, 6-20 "분리 필수" 재검토). nightly는 새벽 배치라 폴링 288회/일(6-20 사고)과 규모 다름 + 낮 작업과 시간대 분리. 실제 호출량=리포트 설계 함수라 책상계산 불가 → 1박 mock으로 측정(계획 W4 실측 시작점).
- **리포트 뼈대 = 활동량 + 활동 시간대 (+탈피).** eat/drink 미세행동=VLM 천장(4레버 종료)이라 "관찰됨" 수준만, 배변=클래스 폐기(v4.0)라 제외. 북극성 강점존(활동량/일주기)과 정합. SOT §4 다정한 페르소나 프롬프트(`petcam-ai-pipeline.md §4-2`)는 뼈대 검증 후 문체만 교체.
- **접근 = mac-runner 스모크(4연결점) 확장** → 1~2h 윈도우 clip 분석/분류 → slack 활동요약. 작업 레포=**petcam-nightly-reporter**(코드 0), 복붙=mac-runner, 레시피 이식=petcam-lab(`_extract_frames_clip.py`·`build_system_prompt('crested_gecko','v4.0')`·`r2_uploader` 패턴).

**계획서:** `~/petcam-nightly-reporter/specs/plan-window-worker-mvp0.md` — W0(부트스트랩+스모크 이식) ~ W5(launchd). 실제 코드 박음, TDD는 순수로직(timewin/summarize)만, 외부연결은 walking-skeleton 수동검증. writing-plans 스킬 준수.

**✅ 완료 (2026-07-07 새벽) — MVP-0 구현 + 맥미니 배포:**
- W0~W5 전부 구현·검증·커밋 8개 push (nightly repo `f4e9092`~`7dcfd78`). W3 이미지 입력 방식 확정 = 경로나열+`--allowedTools Read`+`--add-dir`+`--append-system-prompt-file`+`--model sonnet`+`--output-format json`.
- **핵심 재설계**: W3 스파이크 clip당 **~12만 토큰** 실측 → 원안(전량 claude)은 한도초과 → **W4a 뼈대(활동량/시간대=motion_clips DB, claude 0회) + W4b 행동샘플(`SAMPLE_TOP_N` top-N claude)** 분리. `summarize_activity`/`summarize_behaviors`.
- **맥미니 배포 완료**: push→clone→uv sync→.env scp→수동검증(5a 뼈대/5b 파이프)→launchd. RunAtLoad+00시 `exit 0`, claude 5회 성공, Slack 카드. launchd 야간 **22/00/02/04시**(사용자 인사이트=시간분산으로 한도 피크분할 + 새벽 미사용 독점).

**다음 착수점 = 아침 1박 실측 확인:**
1. 밤새 Slack 카드(오늘 02/04시 + 이후 매일 22/00/02/04) 활동량/시간대 패턴.
2. ⭐ **claude 한도 소모** — 워커(4회×5clip≈20/night)가 본인 작업 지장 줬나. `claude-subscription-quota-shared` 실측(→분리 여부 결정).
3. 튜닝: `SAMPLE_TOP_N`(현재 5)·스케줄. + "특이행동 없음" 계속(top5 다 moving)이면 샘플 방식 재고(탈피/음수 드물어 상위N 누락).
4. 끄기: `launchctl bootout gui/$(id -u)/com.petcam.nightly-reporter` (맥미니).

**상세:** `~/petcam-nightly-reporter/specs/plan-window-worker-mvp0.md` · nightly `specs/architecture.md`(상위설계) · SOT `petcam-ai-pipeline.md §4`(리포트)·`§11`(레포 토폴로지)

---

## 🆕 2026-07-02 — 북극성(먼 미래 최종목표) 확정 + 다음 세션 3트랙 정렬

**완료 (전략 아이디에이션, 코드 0 — 문서+메모리):**
- **petcam 북극성 확정** (`docs/petcam-north-star.md` 신규, 커밋 대기 — 사용자가 `tera-ai-product-master/products/petcam`로 이관 가능):
  - 정체성 = **"양서파충류의 모든 행동을 세계에서 가장 정확하게 읽어내는 행동분석 AI"**. 이상감지는 정체성 아니라 **응용**(정상 알아야 이상 앎 + 편향없는 완전 로그=미래 응용 원본). 데이터를 '파는' 회사 아니라 '아는' 회사.
  - 구조 = 파운데이션(행동분석) + 응용(이상신호·사육최적화·제품검증·종표준) + 자산(데이터셋=복제불가 moat). 3요소 = 측정환경(접점)·데이터셋(moat)·측정AI(엔진), 환경형태 안 박음(YAGNI).
  - **고객 피벗**: B2B 연구·실험 시장 작아 → **동물병원 연계(B2C, "아플때 진단근거"=WTP해결, 진단 안 하고 근거만=의료주장 회피)** + **무인 호텔링(B2B, 유통 모니터링노드 — 배송허브·판매보관으로 가동률)**. 연구·제약=데이터 앵커. 호텔링 하이브리드(직영→AI공급), 리테일 제휴, 우리는 오프라인 주체 아님.
  - 가드레일: 의료진단 주장 금지 / 하드웨어·오프라인 안 무겁게(SW·데이터 회사로 남음) / 완벽주의 함정(미세시각구분 천장, 활동량·일주기·은신=강점존).
  - 근거: 전남대 박혜린 박사논문(2026, 지도 성하철) — 활동량·일주기·은신=검증된 스트레스지표, 지금 사람이 수동측정=자동화 대상. Ch1 온라인 유통 활발=배송허브 근거. 환경부 R&D(RS-2018-KE000335) 접점. (메모리 `north-star-vision`)
- **⚠️ 시간축 구분**: 북극성(활동량/일주기 강점존)은 **먼 미래 나침반**이지 당장 우선순위 아님. 당장은 미세행동 분류(현 제품 근간)를 푼다 — 사용자 명시.

**다음 세션 할 일 3트랙 (사용자 지정, 2026-07-02):**
1. **미세행동 완벽분류** (petcam-lab/rba-worker) — ⚠️ **경로부터 결정.** VLM 4레버(입력·프롬프트·모델·ROIcrop) 다 천장 확인됨(`v1-drinking-close`·`roi-crop-close`) → "완벽분류"를 VLM 더 갈기(같은 벽)가 아니라 **비-VLM(영상네이티브·YOLO evidence·HITL·메타)** 경로로 갈지 먼저 못 박기. spec `feature-rba-evidence-based-feeding-drinking.md` 본작업 + Gate 0(미스팅 카메라 육안).
2. **gecko-vision-gate 카메라 가동** (gecko-vision-gate 레포 — petcam-lab서 직접 안 건드림) — v1 안정화됨, 곧 카메라 연결 → clip 유입 시작 → gate 자동 prelabel 검증. 카메라 가동 ↔ mac mini gate 자동화 한 세트.
3. **mac mini 자동화 준비** (launchd, 각 레포/맥미니) — ⚠️ 블로커 먼저: ① **claude 구독 한도 분리**(전용계정/API key/저빈도 — 워커 폴링이 본인 claude 한도 공유·초과, `claude-subscription-quota-shared`) ② launchd + PATH 함정(`cron-launchd-keychain`). = 아래 **06-20(2) 블록 맥미니 Phase 1 착수점과 동일 트랙**.

**상세:** `docs/petcam-north-star.md` · 메모리 `north-star-vision` · (미세행동) `v1-drinking-close`·`roi-crop-close` · (맥미니) 아래 06-20(2) 블록

---

## 🆕 2026-06-20 (2차) — 맥미니 Phase 0 완전 종료 (재부팅 생존 + PATH 버그 + 한도 발견)

**완료 (mac-runner `ce30721`→`c3f04e2`, petcam-lab 문서정리):**
- **맥미니 본체 Phase 0 검증 ✅** — clone(PRIVATE→gh auth) → uv sync → .env(3키) → smoke ✅ → launchd 등록 → **재부팅+자동로그인 생존 ✅**(23:01 KST). "상시 워커" 자격 완성.
- **★ launchd PATH 버그 진단·수정·push** (`c3f04e2`) — launchd 트리거 시 `❌claude`(셸은 ✅). 로그 `No such file 'claude'`=FileNotFoundError. 원인: uv(`~/.local/bin` standalone)≠claude(`/opt/homebrew/bin` brew) **다른 bin**인데 install-launchd.sh가 plist PATH에 uv 디렉토리만. → `command -v claude`도 잡아 추가+가드. 맥북은 둘 다 brew bin이라 우연히 통과했던 환경종속. (메모리 `cron-launchd-keychain` PATH함정 정정)
- **FileVault off + 자동로그인** — 무인 부팅에 자동로그인 필요한데 FileVault ON이 자동로그인 원천차단(macOS 의도). 보안 trade-off(맥미니 .env service_role 평문→물리도난 노출) 설명 후 사용자 **FileVault off 선택**(집 물리안전 전제).
- **★ claude 구독 한도 공유 발견** — 재부팅 후 첫1회만✅ 이후❌ 반복 → 셸 직접 "session limit resets 1:10am" = **구독 한도 초과**(코드무죄). 맥미니 5분폴링(288회/일)+본인 claude작업이 **같은 구독 한도 공유**. 1:12 리셋 복귀로 확증. **검증 끝났으니 스모크 bootout**(한도 그만 소모). 모든 맥미니 워커(gate/nightly) 공통 제약. (메모리 `claude-subscription-quota-shared` 신설)

**다음 세션 착수점:**
1. **Phase 1 워커 선택 + 착수** — nightly-reporter 1순위(README). launchd 패턴 이식(⚠️ 야간 분할은 `StartCalendarInterval`=절대시각, mac-runner `StartInterval`=N초마다와 다름).
2. **🥇 claude 한도 분리 설계** (Phase 1 선행) — A.전용계정 / B.종량제 API key(`ANTHROPIC_API_KEY`) / C.저빈도. 워커 합산 호출수 계산부터.
3. **smoke.py 진단 개선** (Quick) — stdout도 로깅(한도 메시지가 stdout이라 놓쳤음, 로그에 rc=1만 보였음).
4. **자매레포 PATH 전파** — gate/nightly가 install-launchd.sh 베껴갈 때 uv·claude 이중 PATH(⚠️ gate는 claude 호출 없어 uv만).
5. (P2) 보안: service_role→좁은 권한 키 / SOT `petcam-ai-pipeline §11`에 mac-runner+launchd 반영 / preflight.sh(다음 워커 셋업 시).

**상세:** `specs/feature-mac-mini-scheduled-claude-runner.md` · 메모리 `cron-launchd-keychain`·`claude-subscription-quota-shared`

---

## 🆕 2026-06-20 — 맥미니 워커 Phase 0 스모크 맥북 검증 + launchd 전환 + GitHub push

**완료 (별도 레포 [`S-Soo100/petcam-mac-runner`](https://github.com/S-Soo100/petcam-mac-runner) private, 커밋 `cc93c35`→`ce30721`):**
- **mac-runner 레포 골격 = 참조 스켈레톤** (공유 라이브러리 아님): `smoke.py`(supabase 핑 httpx + `claude -p` subprocess + slack webhook POST, 4연결점 한 줄 관통) + `install-launchd.sh` + README + uv. gate/nightly는 import 아닌 **복붙으로 패턴 재사용**(자매 레포 토폴로지 일관). 맥북에서 짜고 git 이관(petcam-lab 통째 압축 ❌ — MAC_MINI_DEV_ENV 마이그레이션X·경로 다름·.env/.venv 함정).
- **Phase 0 맥북 검증 6/6** — `✅ supabase · ✅ claude · HH:MM KST`. 수동 + launchd 무인반복 2사이클(RunAtLoad 즉시 + StartInterval 5분).
- **⚠️ 핵심 발견: cron→launchd (keychain 세션)** — 처음 cron 5분 시도 → `❌ claude (Not logged in rc=1)`. 진단: claude 구독 인증=macOS **login keychain**(`.credentials` 파일 아님), **cron 데몬=GUI 세션 밖→keychain 접근 불가**. **LaunchAgent=GUI 세션 실행→keychain OK**(같은 스크립트 cron ❌→launchd ✅). 대안 `claude setup-token`(`CLAUDE_CODE_OAUTH_TOKEN` env, 구독 커버)도 있으나 사용자가 keychain 재사용(launchd) 선택. **모든 맥미니 워커 공통 교훈.** (메모리 `cron-launchd-keychain`)
- **확인 선행 해소**: Slack webhook(mac-worker-app→#mac-bot 발급·실물검증) + 맥미니 claude/uv 설치(사용자) + 운영형태=**자동로그인 GUI 상시**.
- **스펙 정정**: `feature-mac-mini-scheduled-claude-runner.md` §3/§4 (cron→launchd 필수, 완료조건 맥북 ✅, 미해결질문 해소).

**다음 세션 착수점:**
1. 🥇 **맥미니 Phase 0 재검증** (사용자 직접, 맥미니에서) — `git clone https://github.com/S-Soo100/petcam-mac-runner` → `uv sync` → `.env`(맥북 값 복사: `SUPABASE_*`·`SLACK_WEBHOOK_URL`) → `claude -p "say hi"`로 **로그인 확인**(설치≠로그인) → `chmod +x install-launchd.sh && ./install-launchd.sh` → `tail -f /tmp/mac-runner-smoke.log`에 `✅ claude` 뜨면 → **`sudo reboot` 1회 → 재부팅 후 자동복구 확인**(RunAtLoad+자동로그인이 살아나야 "상시 워커" 자격 완성) → Phase 0 종료.
2. **Phase 1 워커 선택** (스모크 통과 후) — gate / nightly-reporter / 신규. **보류.** ⚠️ Supabase 라벨 쓸 때 gate `clip_prelabels`와 쓰기영역 분리(§11.3).

**병행 트랙 (06-18서 계속):** nightly Step 1~3 골격(terra `motion_clips` B쿼리) · eval-0617 blind(시험지+quality_tag 선행) · dataset-197 zip 송부(사용자).

**상세:** `specs/feature-mac-mini-scheduled-claude-runner.md` · 레포 `S-Soo100/petcam-mac-runner` · 메모리 `cron-launchd-keychain`

---

## 🆕 2026-06-19 — 맥미니 스케줄드 Claude 워커 셋업 착수 (개념 교육 + 계획 정렬)

**완료 (이 커밋):** 아직 코드 0 — 공부 + 합의 단계.
- **맥미니 주기 Claude 워커 개념 교육 + 계획 정렬** (`specs/feature-mac-mini-scheduled-claude-runner.md` 신규):
  - **멘탈 모델**: 맥미니=서버 아니라 **클라이언트**. 집 NAT 뒤라 inbound 불가→outbound만→서버 push 못 받음→**폴링 강제**. 루프 = 깨어남→"할 일?" 폴링(Supabase/R2)→처리(claude)→결과 쓰기→잠듦.
  - **폴링 워커 3조각**: ① 스케줄링(무한루프+sleep ≈ setInterval / OS 스케줄러 launchd·cron, KeepAlive 자가복구) ② 서버 폴링(Supabase DB todo / R2 클립, +처리완료 표식 필수) ③ Claude 호출(API 종량제 vs CLI headless 구독).
- **핵심 결정 6개**:
  1. Claude 호출 = **형태② CLI headless** (`claude -p`, 구독 커버 — Gemini 퇴역→Claude 피벗 연장).
  2. 1단계 = **walking-skeleton 스모크** — 라벨링 로직 전에 연결점(스케줄러·Supabase·Claude·Slack) 생사부터 검증.
  3. Slack 전송 주체 = **스크립트가 쏜다**(claude 아님) — 단계별 진단 분리.
  4. 만드는 순서 = **슬랙부터 거꾸로** — 성공 신호 창 먼저.
  5. 스케줄러 = 스모크 **cron 5분** → 정착 **launchd**.
  6. Slack = **Incoming Webhook**(curl POST 한 방).
- **Phase 1 흐름(사용자 제시)**: Supabase todo → R2 영상 → 조회 → Supabase 라벨 쓰기. ⚠️ 깃발: gate `clip_prelabels`와 **쓰기영역 분리**(§11.3).

**다음 세션 착수점:**
1. ⏳ **확인 선행 (사용자)** — 스모크 출발선 2개: ① Slack Incoming Webhook URL 발급됐나(없으면 발급부터) ② 맥미니에 `claude` CLI / `uv` 설치됐나.
2. **Phase 0 스모크 구현** (위 확인 후) — 슬랙 webhook 1줄 → supabase 핑 → `claude -p` → 종합 1줄 자동전송 → cron 5분 등록. 완료조건 6개 = 스펙 §3.
3. **Phase 1 워커 선택** (스모크 통과 후) — gate / nightly-reporter / 신규 중. **보류**.

**병행 트랙 (06-18서 계속):** nightly Step 1~3 골격(terra `motion_clips` B쿼리) · eval-0617 blind(시험지+quality_tag 선행) · dataset-197 zip 송부(사용자).

**상세:** `specs/feature-mac-mini-scheduled-claude-runner.md`

---

## 🆕 2026-06-18 — 펌웨어 R2 계약 + dataset 송부 v4.0 + DB sync 유령 정리

**완료 (커밋 `5af39dd`, push✅):**
- **nightly indexer R2 layout 설계 → B방식 확정** — 야간 윈도우 clip 조회 = R2 prefix listing(A) 아닌 **camera_clips.started_at BETWEEN + r2_key IS NOT NULL 쿼리(B)**. object store(R2/S3)는 prefix만 빠르고 시간범위 약함, camera_clips가 이미 "R2 객체들의 시간 인덱스". "독립 공장"(behavior_logs 종속X) 원칙과 양립(camera_clips=입력 인덱스). ⚠️ backfill 81건이 started_at에 등록시각(06-12) 박은 오염 발견 → started_at=녹화시각 계약 필요. (메모리 `object-store-time-index`)
- **펌웨어 R2 clip 등록 계약 핸드오프** (`docs/handoff-prompts/camera-firmware-clip-contract.md`, 커밋 5af39dd): ESP32-P4 캠 직접 Supabase 등록. **started_at=녹화 시작 UTC(등록시각 아님)**. 등록흐름 row→승인→R2업로드→r2_key 채움(nightly는 r2_key NOT NULL로 완료분만). camera_clips 필드표 + r2_key 규칙(`clips/{camera_id}/{date}/{HHMMSS}_motion_{uuid}`) + 보안(service_role 임베드 금지). **전달 완료 → 협의 3문항 회신 대기**(camera_id/user_id 프로비저닝·NTP·유령row 청소).
- **dataset-203 전문가 송부 패키지 v4.0 갱신** (storage/ gitignore→zip 송부): README 전면 재작성(v3.6.1/202/Gemini → **v4.0/197/Claude + frame-side 4레버 천장 결론**) + `prompt_v4.0.md` 신규(production `build_system_prompt('crested_gecko','v4.0')` 출력 박제) + `analyze.py`(프롬프트 v4.0 로드 + CLASSES 7개 + 적응형 frames + `--model sonnet/opus` 별칭). 검증: estimate + 적응형 6장@1080 + 7-class. ⚠️ 데이터셋 197 vs v4.0 측정 186(eval-0617 10건 미측정). (메모리 `run-sot-function-reconstruct`)
- **DB GT sync 4건 = 이미 완료 확인(유령 항목)** — 06-09 "미적용"이 6-13~17 팔로업에 복붙돼 끌려왔으나 실측(execute_sql)하니 **06-12 이미 완료**(action=moving + 정정 notes). 메모리+next-session line 25 정정. (메모리 `recalled-memory-verify`)

**다음 세션 착수점:**
1. 🥇 **nightly Step 1~3 골격** (지금 착수 가능, 권한 관문 없음) — `~/petcam-nightly-reporter` pyproject + indexer(**terra `motion_clips` started_at B쿼리** ← camera_clips 아님) + motion_scan(`motion_score>0`). ✅ **`motion_clips` 같은 Supabase에 있어 이미 접근 가능**(2026-06-18 실측 21건, 어젯밤 클립 들어옴 — terra "별도 프로젝트"는 부정확). B쿼리 실데이터 즉시 검증.
2. ✅ **계약 v1 확정**(2026-06-18 terra 회신, `docs/handoff-prompts/camera-firmware-clip-{contract,reply}.md`): 펌웨어 서버경유 DB-last(유령 row 불가)·started_at SNTP UTC 충족·**옵션1**(리포터 terra `motion_clips` 직접조회). **`file_path` 마이그레이션 불필요**(HW캠은 camera_clips 안 씀, camera_clips=레거시). 후속: SOT `petcam-ai-pipeline §11`(terra-server 편입) + nightly `architecture §10`(motion_clips 조회+스키마매핑 `has_motion↔motion_score`/`owner_id`/`enclosure_id`) 갱신.
3. **eval-0617 blind 평가** (drinking 24 V1 재측정) ← ⚠️ 시험지 + **quality_tag 전수 태깅(사용자 직접**, eval-0617 10건 전부 1206x2622 handheld) 선행.
4. (사용자 직접) dataset-197 zip 송부 · gecko-vision-gate 파인튜닝(진행중) · quality_tag 태깅.
5. (P2) RBA evidence Gate 0(미스팅 카메라 감지 clip 육안) · (P3) `5a34267c`·`ce9bab20` GT 재검토 + register_eval_batch.py 통합(0608/0615/0617 3스크립트, automation-scout 제안).

**상세:** `docs/handoff-prompts/camera-firmware-clip-contract.md` · `storage/dataset-203/README.md` · 메모리 `object-store-time-index`·`run-sot-function-reconstruct`·`recalled-memory-verify`

---

## 🆕 2026-06-17 — RBA 파이프라인 통합 설계 + eval-0617 (자매 레포 2개 편입)

**완료 (4커밋, petcam-lab push✅):**
- **eval-0617 평가셋 등록** (`scripts/register_eval0617.py`, 커밋 `39d2e53`): `Downloads/new-data-2026-06-17` 10건(drinking7/eating_paste2/hand_feeding1) → R2(`clips/eval-0617/`)+camera_clips+behavior_logs+manifest. 네이밍 `{gt}__na__{clip8}.mp4`(eval-0615 패턴, R2=manifest 일치). **manifest 187→197**(drinking 17→24 공백보강·paste 17→19·hf 28→29). 회귀셋 185 동결 유지(전체 197에만). 전부 **1206x2622 세로 handheld**(fps 38~60, quality_tag 빈칸=사용자 육안 대기). dry-run/--apply·file_path 멱등.
- **RBA 파이프라인 통합 아키텍처** — 두 자매 레포를 SOT 4-레이어에 편입:
  - **통합 SOT**: `tera-ai-product-master/docs/specs/petcam-ai-pipeline.md §11`(신규, 커밋 `84ccf44`). 4-레이어↔레포 매핑 + R&D/운영 분리 + Gate 신설 + detector 로드맵 + Gemini→Claude.
  - **gecko-vision-gate** (`specs/architecture.md`, git init `b3689fb`): R2 업로드마다 **상시 자동 prelabeler**(게이팅 폐기). 폴링(mac-mini NAT), evidence baseline 북극성, RF-DETR v0(gecko 1클래스)→evidence 멀티클래스, `clip_prelabels` 계약.
  - **petcam-nightly-reporter** (`specs/architecture.md`, git init `ce3d4bc`): 독립 풀파이프 **공장**(lab 레시피 소비). Claude Code CLI(구독, Codex 대체), **야간 분할 3~4회+06 종합**, mac-mini 24h, Gate prelabel 재활용.
- **핵심 설계 결정 (재논의 금지)**:
  1. **Gate = 상시 prelabeler** (VLM 게이트키퍼 아님) — VLM과 디커플링, 모든 영상 메타 강화→VLM 힌트. 비용절감 게이팅 폐기. "VLM 호출은 비싸지만 prelabel은 싸고 빠르다."
  2. **R&D/운영 단방향 분리**: lab(연구소=정확도/레시피) → nightly(공장)/gate(부품). 운영이 연구 역수정 X, 레시피만 단방향.
  3. **worker 공존 = 스토어별 쓰기영역 분리**: Supabase=Gate만 쓰기 / R2 reports=nightly만 쓰기 → write-write 충돌0. 느슨한 의존+멱등+flock.
  4. **nightly 야간 분할**: 8시간 한방 X(한도/지연/전량손실) → N윈도우 incremental+06 merge. peak 부하 분산(공존 유리).
  5. **Gemini→Claude 동기화**: SOT §2/§4 Gemini Flash=historical, 현 엔진 Claude(§11.6).

**다음 세션 착수점:**
1. **gecko-vision-gate Phase 0** — RF-DETR core 설치 + 로컬 mp4 1개 inference 검증(architecture.md §7). seed 라벨 = `storage/dataset-203/`(197) 활용.
2. **nightly-reporter Step 1~5** — pyproject 골격 + R2 indexer + motion_scan + frame_sampler(lab 적응형 레시피) + bundle. mac-mini 핸드오프 전 로컬 PoC.
3. **eval-0617 blind 평가** (⚠️ 시험지 필요) — drinking 24로 늘어 V1 재측정 가치. 적응형@1080 Sonnet v4.0. quality_tag 전수 태깅(사용자 직접) 선행.
4. (P2) 원본 정리(`Downloads/new-data-2026-06-17`). (✅ **DB GT sync 4건 이미 완료** — 2026-06-18 실측: `05da625c`·`2420abd8`·`987c7b5d`·`ff1ecb03` 모두 DB·manifest 둘 다 moving. 06-12 적용분(line 141)이 06-13~17 팔로업에 유령으로 끌려온 것 — 액션 없음)

**상세:** 각 레포 `specs/architecture.md` · `petcam-ai-pipeline.md §11`

---

## 🆕 2026-06-16 (2차) — ROI crop close (frame-side 입력 레버 종료)

**완료 (커밋 대기):**
- **계층줌인+ROI crop 기획 + C1 PoC → decision `close`** (`specs/experiment-hierarchical-zoom-roi-crop.md`, `experiments/roi-crop-center/`):
  - center ROI crop(**원본 프레임** min(짧은변,1080) 정사각, 시간밀도는 적응형과 동일 통제 = crop만 변수) Sonnet v4.0 blind, 급여 3종 56건(drinking17/paste17/prey22) paired vs 적응형@1080.
  - **결과: 급여경계 71.4%=71.4% (Δ+0.0%p), paired recovered2/broken2/순0 → close.** 4K급 10건 순0 — **변동 4건 전부 저해상(<720) noise**(긴변 크롭 프레이밍), 고해상 무변화 = crop "공간해상도↑" 가설과 정반대.
  - **데이터가 1차 병목**: 56건 중 4K급 10건뿐, **prey 22건 중 4K급 1건**(짧은변 중앙값 476). 미세접촉 영상이 대부분 저해상 → crop으로 키울 원본 디테일 부재.
  - 신규 자산: `scripts/_extract_frames_clip.py --roi-crop`(원본 crop→1080 cap), `scripts/_score_roi_crop.py`(적응형 baseline paired + 해상도 층화).
- **frame-side 입력 레버 완전 종료** — V1(풀프레임→1080 다운스케일 천장) + ROI crop(원본 ROI-local 확대 천장) = 정지프레임 VLM 입력의 **마지막 카드까지 소진**. 입력·프롬프트·모델·ROIcrop **4레버 다 천장**. 학습노트 §6 표 "계층줌인+ROIcrop" = ❌. (메모리 `roi-crop-close-frame-side-terminal`)

**다음 1순위 (frame-side 종료 → 패러다임 전환):**
1. 🥇 **RBA 비-VLM evidence layer** — drinking/eating_paste/eating_prey **유일한 길**. `feature-rba-evidence-based-feeding-drinking.md` 본작업(미스팅/먹이투입 메타 타임스탬프 매칭 + prey stalk→lunge→snap motion §6.5 + HITL, 객체검출 fuzzy 보너스). 사용자 트리거 대기.
   - **⚠️ 착수 전 Gate 0 (§7 Phase 7, 미실행)**: 미스팅이 카메라에 찍히는지 clip 1~3건 육안 → 감지가능=`cv_roi` 자동감지 트랙 / 불가=스케줄+원탭 폴백으로 §5.5 설계 확정. **DB 스키마 설계 전에 이 분기부터.**
   - **ROI crop close 함의(spec §4.5 반영)**: "YOLO bbox crop→VLM 재판정으로 정확도↑" 경로는 데이터가 기각(4K급 순0). YOLO는 좌표 evidence/투입 컨텍스트 매칭으로만.
2. (P2) quality 전수 태깅 untagged 83건(**사용자 직접**) · DB GT sync 4건(`05da625c`·`2420abd8`·`987c7b5d`·`ff1ecb03` drinking→moving).
   - **eval-0615 2건 편입 결정**: akze3466 V1 drinking 0.82 ↔ 이번(roi-crop baseline) moving 0.72 흔들림 → temperature 0 측정 확보 전까지 **187 전체에만 포함, 회귀셋 185 동결 유지**(노이즈 샘플 회귀셋 혼입 방지).
3. (🔒 보류) conf 캐스케이드 temperature 0 재측정(키 확보 AND production 재가동).

**상세:** `experiments/roi-crop-center/REPORT.md` · 메모리 `roi-crop-close-frame-side-terminal`

---

## 🆕 2026-06-16 — C 캐스케이드 + conf 심화 + B2 prey spec + 영상분류 학습

**완료 (커밋 `d4bad5c`~`7233a61`, push):**
- **C 캐스케이드 시뮬** (`experiments/cascade-opus-sim/`, 인퍼런스 0) — decision `클래스 기각 / conf viable · prey+drink 비-VLM`:
  - 표적 클래스 라우팅(R1 shedding/R2 vuln) = 같은비율 random 동률 → 기각. 격차 6건이 5클래스 분산(moving3·prey2·paste1·drink1·unseen1) = **P4(202·v3.6.1) 단일 실패모드와 정반대**.
  - **conf<0.7 16% Opus 호출 = ceiling(88.7%) 100% 회수** (Sonnet 오답 conf 중앙 0.70 < 정답 0.88). P4("conf 2.3배 비효율")의 정반대 — v4.0 잔여오답이 저신뢰 모호 케이스.
  - **D2 (B2 스코프 확정)**: eating_prey 22%·drinking 20%만 Opus 회수 → **모델불변 시각한계**. prey가 더 심각(quality-invariant).
- **conf 심화 진단** (`scripts/_cascade_conf_deep.py`, REPORT §7) — decision `조건부 유효 · temperature 0 재측정 키-blocked 보류`:
  - calibration(Sonnet conf<0.6=정확도 33% 오답집중) + threshold robust(0.6~0.95 plateau).
  - **실제 가격 r=1.67** (Sonnet $3/$15 · Opus $5/$25): conf<0.6 30%·conf<0.7 25% 절감(Opus 단독 대비). 처음 "ceiling 회수" 흥분은 r≈5(70%) 암묵가정 — Claude 가격차 좁아 30%가 천장.
  - temperature 0 재측정 = **Sonnet만**(Opus 4.8 sampling param 400). `ANTHROPIC_API_KEY`/`ant` 인증 부재 + production 셧다운 → **🔒 키-blocked 보류** (사용자 결정). 재개 = 키 확보 AND production 재가동.
- **B2 — RBA spec에 eating_prey 통합** (`feature-rba-evidence-based-feeding-drinking.md` §4.5/§6.5, drinking 동형): 먹이 투입 메타 + stalk→lunge→snap 행동모양 1순위, YOLO 객체검출 fuzzy 보너스(OWLv2 47.5% 교훈). hand_feeding 구분 = 투입 방식(손/도구 visible→hf). `specs/README` 갱신.
- **영상 분류 학습노트** (`docs/learning/video-classification-learning.md`): 파이프라인 5단계 + 적응형 프레임 추출 코드(clamp·구간중앙·ffmpeg seek) + **정지프레임 VLM 천장**(시간밀도 ⊥ 공간해상도, 빠른 혀 못 잡는 이유) + 입력 트릭 평가표. 사용자 학습 + §7에 다음 기획 골격.

**다음 세션 즉시 착수 (🥇 사용자 지정 1순위):**
1. 🥇 **계층 줌인 + ROI crop 기획 + PoC** — **정지프레임 VLM 천장을 넘는 유일한 frame-side 레버.** 1차 적응형@1080 "의심 구간" 검출 → 2차 입/혀 ROI crop 확대 + 촘촘히 재샘플(**시간밀도↑ AND 공간해상도↑**, 두 축 동시). 상세 골격 = 학습노트 §7. ⚠️ 걸림돌: 입/혀 자동검출(YOLO custom, OWLv2 47.5% 교훈) + 1차 트리거를 ROI-local motion으로 잡아 닭-달걀 회피(global motion은 P2서 미세행동 못 잡은 전례). **V1이 닫은 "전체 프레임 입력레버"와 다른 "ROI 국소 확대" 미답 레버** — VLM/비-VLM 경계. spec 기획 → research-testing 시험지 → PoC.
2. (P2) **quality 전수 태깅** — untagged 83건 육안, **사용자 직접**(self-bias 방지).
3. (🔒 보류) conf 캐스케이드 temperature 0 재측정 — 키 확보 AND production 재가동 시.
4. (P2) DB GT sync 4건(`05da625c`·`2420abd8`·`987c7b5d`·`ff1ecb03` drinking→moving, Supabase SQL).

**상세:** `experiments/cascade-opus-sim/REPORT.md` · `docs/learning/video-classification-learning.md` · 메모리 `class-quality-sensitivity`·`v1-drinking-close`·`cascade-routing-signal-model-version-dependent`

---

## 🆕 2026-06-15 — V1 close + Opus 측정 + B1 quality_tag 층화 (평가셋 187)

**완료 (커밋 `677fdda`~`574336f`, push):**
- **V1 drinking 표적검증 → decision: `close`** (`experiments/v1-drinking-targeted/`): 적응형@1080 v4.0, pos 15 + neg 6. drinking recall 11/15. 누출 4건(`7124cebe`흐림·`685911a0`흐림·`b5637a1a`원거리·`f4b33f32`자세) 전부 시각부재, ROI여지 0. v40-regression 재활용 + 풀해상도 육안 재분류. **입력레버는 contact→적응형@1080에서 이미 당겨짐**(회복5/퇴행3), 그 이후 헤드룸 0.
- **핵심 결론 — 입력/프롬프트/모델 = 같은 정지프레임 VLM 패러다임 천장.** drinking 추가개선 = 비-VLM(영상네이티브/메타 분무타임스탬프/HITL/YOLO). (메모리 `v1-drinking-close`)
- **occlusion-check 진단 폐기**: "3369d723=부분가림"·"6a24c2e6=입력해상도" 부정확 확인 → 육안 재분류가 SOT. drinking 누출 4건 전부 GT 유효(제거하면 cherry-pick, 3369 제거 제안 철회).
- **negative control 과탐 1/6** (`a3a453c3` licking-own-face→drinking) — 게이트(≤1) 통과, 경계. v4.0 drinking 정의 모니터(다음 회귀 neg 포함).
- **평가셋 품질정책 확정 = 층화 태그**(closeup/handheld-challenging/production-like), 제거 아님.
- **production 카메라 = 상단 대각선 1080p 원거리** 확정 → drinking 미세접촉 구조적 한계, 비-입력 전제 설계.
- **새 영상 2건 등록** (eval-0615): `akze3466`(clip `d6c57474`, Sonnet v4.0 blind=drinking 0.82) + `ju10615`(clip `9e9f164b`, 디스펜서 drinking). 평가셋 185→**187**(회귀셋 185 **동결** 유지, eval-0615 2건 분리). R2+DB+manifest+이동 완료. ⚠️ clip_id가 UUID라 파일명("10615")으로 grep 안 잡힘.
- **Opus vs Sonnet 정확도 측정** (`experiments/opus-sonnet-186/`, decision `Opus 우위`): 적응형@1080 v4.0 blind 186건 → **Opus 4.8 88.7%(165) > Sonnet 4.6 85.5%(159), +3.2%p**. Sonnet 회귀셋 185 = **85.9%** = v40 정확일치(채점 무결 + 재활용 정합 검증). P1(frames-10·v3.6.1)에서도 Opus +3%p → 입력·프롬프트 바뀌어도 격차 일관 = 노이즈 아님. discordant 8:2 Opus. **production 전환은 비용·지연 trade-off 별도** → 캐스케이드(Sonnet 기본 + 저신뢰/특정클래스만 Opus) ROI 후보. (Opus 배치 = Workflow 2회 + 누락 10건 Agent 재배치, 합격기준 사후변경 없음)
- **평가 정책 확정** (CLAUDE.md 룰4): **정확도·모델 측정 = manifest 전체 187 기본**(앞으로 추가분도 자동 포함) / **버전 paired 회귀 = 185 동결**(프롬프트 v4.0 85.9%와 직접비교용). eval-0615 2건은 clean/쉬운 샘플이라 quality_tag로 난이도 구분 예정(아래 #1).
- **M1/M3 not-proceed**: V1 close + M0 hold로 몽타주 트랙 전체 종료.

---

### B1. quality_tag 층화 완료 (커밋 `bac7ea1`·`574336f`, 2026-06-15 2차)

- **manifest 187 quality_tag + tag_basis 2컬럼** (`_add_quality_tag.py`, 멱등). drinking 17 전수(visual: closeup 7 / handheld-challenging 7 / production-like 3) + cam-motion 71 production-like(heuristic 출처추정) + uploaded·eval-0608 99 untagged. tag_basis로 육안/추정/미태깅 신뢰도 구분. **cherry-pick 대안 = 제거 아닌 층화 태그.**
- **`_score_by_quality.py`** — Opus/Sonnet 186 예측 quality 층화(새 인퍼런스 0). `opus-sonnet-186/REPORT.md` §7 부록.
- **핵심 발견 — 클래스별 quality 민감도:**
  - **drinking = quality-sensitive**: 실패가 handheld-challenging만 (closeup·prod 100%). 입력 좋으면 풀림 (V1 일치).
  - **eating_prey = quality-invariant**: 오답 closeup 2·handheld 3·production 4 골고루. 게코 선명해도 먹이객체(귀뚜라미) 작고 어두워 안 잡힘 = drinking보다 깊은 시각한계. Opus 에스컬도 →moving.
- **모델격차 hard 집중**: drinking handheld Opus 4/7 vs Sonnet 3/7, cam-motion +4%p, 쉬운 건 동률 → 캐스케이드(hard만 Opus) 정량 근거.
- **⚠️ selection bias**: 오답 16만 태깅한 수치(closeup 38% 등)는 순환논리 — quality 정확도는 전수 태깅 drinking 17만 신뢰. (메모리 `class-quality-sensitivity`·`selection-bias-error-only-tagging`)
- **B2 범위 확장 결정**: drinking 단독 → **drinking + eating_prey 묶음**(둘 다 비-VLM 버킷, prey가 더 심각).

**다음 세션 즉시 착수 (우선순위 — C를 B2보다 먼저):**
1. ✅ **manifest quality_tag** — 완료(B1, 위).
2. 🥇 **캐스케이드 시뮬 (C)** (Quick·선행조건 0, P1) — `_sim_cascade.py` strong을 Opus로 교체(`experiments/eval-frames-full/opus48_blind.jsonl`) + Sonnet 기본 라우팅(R1 shedding-trigger ~ R4 disagree + **eating_prey-trigger** 추가). **C를 B2보다 먼저** = 인퍼런스0·즉시가능 + "캐스케이드가 eating_prey 회수하나"가 B2 범위(prey 비-VLM 필요성) 결정. ⚠️ opus 186 sample_list는 keys 매핑 별도. 인퍼런스 없어도 의사결정이라 TEST-SHEET 간단히. → `experiments/cascade-opus-sim/REPORT.md`.
3. 🥈 **B2 비-VLM spec** (Standard, P1) — C 결과 후. `feature-rba-evidence-based-feeding-drinking.md`에 **eating_prey 섹션 추가**(먹이객체 YOLO 검출 → hand_feeding 구분). drinking 스코프 In/Out 유지. `specs/README.md` 갱신.
4. **quality 전수 태깅** (P2) — 정답 83건(untagged) 육안. **사용자 직접**(Claude 태깅은 self-bias). selection bias 탈출 → 진짜 quality별 정확도. B2/C 후.
5. (P2) DB GT sync 4건(`05da625c`·`2420abd8`·`987c7b5d`·`ff1ecb03` drinking→moving, Supabase SQL) + broken 5 discordant(사용자 영상). (P3) DEFAULT v4.0 승격(production 재가동 시) / `/vlm-regression` 자동화.

**⚠️ 계속 대기:** `5a34267c`·`ce9bab20` 사람 영상(defecating GT 의심).

**상세:** `experiments/v1-drinking-targeted/REPORT.md` · 메모리 `v1-drinking-close`·`input-resolution-micro-contact`·`feedback_eval_set_freeze_no_cherrypick`

## 🆕 2026-06-13 — v4.0 + 평가셋 185 + 연구 테스트 인프라

**완료 (커밋 `7d4f73c`~`b3b05ff`, push):**
- **v4.0 프롬프트 신설** (`web/prompts/backups/{system_base,crested_gecko}.v4.0.md`, `prompt_version="v4.0"` 격리, v3.6.1·v3.5 무손상): defecating/basking/hiding 폐기 → **7-class**, drinking = "물 보임→몸 고정+반복 핥기" 행동패턴 재정의 + 부분가림/클로즈업 보강 + "1회 충분" 폐기 + 장소로 paste 구분. (메모리 `drinking-behavior-pattern-redef`)
- **평가셋 202→185** (`manifest.csv`, `_excluded/` 보존+`manifest.csv.bak-202`): defecating 16 폐기 + `cf698b78` 부적합. GT: drinking15/moving72/paste17/hf28/prey22/shedding29/unseen2.
- **연구 테스트 인프라** (`.claude/rules/research-testing.md`): 의사결정용 테스트 = TEST-SHEET(pre-reg)+REPORT(decision)+`experiments/INDEX.md` 의무. 템플릿 2개. (메모리 `research-test-sheet-report`)
- **M0 몽타주 12변형 스크리닝** (Sonnet 20건, `experiment-claude-montage-v2.md` §7) → **decision hold** — 12변형 전부 frames(12/20) 미달, 2장>1장(셀 해상도=레버) 확인하나 천장 못 넘음. `experiments/m0-montage/REPORT.md`.
- **입력 기준 확정**: frames 긴변 **min(원본,1080) no-upscale**. 추출기 `scripts/_extract_frames_clip.py`(단일/배치, manifest 필터). (메모리 `input-resolution-micro-contact`)
- **drinking 4건 풀해상도 진단**: 입력 해상도가 미세접촉(혀) 1차 병목 — 6a24c2e6=입력해상도/3369d723=부분가림/cf698b78=GT부적합. `experiments/drinking-occlusion-check/`.
- **CLAUDE.md 버전격리 4규칙 피벗 반영** (Gemini 85.5%/202 → Claude/v4.0/185/frames@1080). **fly 워커 셧다운**(scale 0) + **DB GT 4건 sync**.

**⚠️ 사람 영상 확인 대기:** `5a34267c`·`ce9bab20` (defecating GT인데 v3.6.1+v4.0 blind 둘 다 shedding 의심, `_excluded/` 보존 — shedding이면 복원).

**✅ #7 v4.0 회귀 완료 (2026-06-13) — decision: adopt** (`experiments/v40-regression/`):
- 적응형 frames@1080(간격3.5/구간중앙/blind셔플, `_extract_frames_clip.py --adaptive`) 신표준 — 고정10 뒷부분(0~45초만 커버) 손실 버그 대체. Workflow 30 에이전트 blind 배치, 급여경계 채점(`_score_v40.py`).
- 결과: raw 동등 **85.9%**, 급여경계 +0.5%p, 게이트 4/4. drinking 클래스 10→11·누출 5→4·moving 과탐 2→1. broken 5건 전부 drinking 무관(노이즈). **v4.0 = 새 회귀 기준선.**

**다음 세션 즉시 착수 (followup-suggester P1):**
1. **M1 not-proceed 마킹** (Quick Win ~5분) — M0 hold로 M1 candidate 없음을 INDEX+`m0-montage/REPORT.md`에 명시, M3 캐스케이드도 닫기.
2. **V1 drinking 표적 검증** (시험지부터 — 다음 세션 메인, 사용자 지정) — drinking 4건 누출이 입력 한계인지 시각 부재인지 가르는 마지막 측정. **⚠️ 재해석(적응형 채택 후):** 적응형@1080이 cv-frames의 duration-adaptive를 **이미 흡수** → cv-frames(768px/타임스탬프) 신규 제작보다 **적응형@1080을 drinking 16 pos + 16 neg(물 없는 곳 혀 날름=moving이어야)에 표적 측정**이 합리적. recall↑와 FP↑를 **동시 확인**(negative control 필수 — drinking 넓힌 v4.0의 과탐 안전성). 기대 낮음(시각 한계 가능) — 회복=입력레버 잔존 / 실패=입력레버 소진 확정, 둘 다 방향 명확.
- P2: broken 5건 discordant(사용자 영상 직접) + `INPUT-REPR-SPEC.md` / P3: DEFAULT_PROMPT_VERSION 승격(production 재가동시), /vlm-regression 자동화(V1 후)

**상세:** `specs/experiment-claude-montage-v2.md` · 메모리 `drinking-behavior-pattern-redef`·`input-resolution-micro-contact`·`class-retirement-criteria`·`prompt-model-specificity`

## 🆕 2026-06-12 — Gemini 퇴역 피벗 + 계획서 (상세는 스펙)

- **유지 자산**: dataset-203(202건, GT 4건 DB sync ✅ 완료 — drinking 16/moving 72), blind 프로토콜, frames-10 기준선(**모델별** — Sonnet 78.2/Opus 81.2, Fable 85.1·구 81.7%는 historical 참고), 프롬프트 버전 격리 체계 (v3.6.1 고정, v3.6.2=Sonnet 전용 보류)
- **소멸**: Gemini floor 85.5% 게이트, v3.6.2 DEFAULT 승격 트랙, Vertex 전환 검토, P3 full-202 Sonnet 배치(`/tmp/p3_full_batches.json`은 montage-v2 캐스케이드에서 재활용 가능)
- **claude-video** (github.com/bradautomates/claude-video): 검증 완료 — frames 방식과 동일 구조 + YouTube 인제스트. 사용자 결정 = 플러그인 설치(단발/YouTube용) + 추출 레시피 재현(cv-frames 정량 트랙)

## 🆕 2026-06-10/11 — Fable 5 + 약한모델 레버 P1~P4

> "다른 모델(Opus 4.8 등)도 Fable처럼 잘하게 하려면?" 질문에서 출발. 스펙 [`experiment-weak-model-levers.md`](experiment-weak-model-levers.md) (P1~P7, 레버 5종).

**완료 (커밋 `77031e5`·`3a34fdf`·`8c304e0`·`23f31eb`, push):**
- **P1/P1b — 4모델 baseline** (frames 202 blind, 같은 추출프레임·v3.6.1·blind, 모델만 교체): Fable 5 **85.1%** > Opus 4.8 81.2% > Sonnet 4.6 78.2%. jsonl 3개(`{fable5,opus48,sonnet46}_blind.jsonl`, gitignore) + `_score_frames_models.py`. **★ 격차 원천 = Sonnet moving 93→76%**(IR 야간 창백패치를 shedding 으로 과탐) **단일 실패모드**(확산 아님). shedding recall↑인데 정밀도↓=과탐.
- **P4 — 캐스케이드 시뮬**(인퍼런스 0, `_sim_cascade.py`): R1 "Sonnet=shedding 예측만 Fable escalate" **23% 호출로 격차 100% 회수**. conf 단독 2.3배 비효율, random 36%만 → 표적 라우팅 입증. Gemini 청사진=Flash→shedding판정만 Pro.
- **P2 — 입력표현 ⚠️ 가설 기각**(`_p2_extract_keyframes`+`_score_p2`): 모션키프레임 N=20 오답셋 recovered **1/11**·broken 0/9. 모션에너지가 저모션 lick 못 짚음 + close-up 대조군 9/9 vs 원거리 오답 전멸 = **게이팅=공간해상도(시간밀도 아님)**. ceiling 미세접촉 →moving 오답을 **drinking/defecating 과 같은 시각한계 버킷으로 재분류**(프레임트릭 X → 영상네이티브/고해상/HITL). 입력표현 레버(몽타주→프레임 +21%p) **소진**.
- **P3 — 표적룰 ✅**(error-set 단계, `system_base.v3.6.2-draft.md`+`_score_p3.py`): v3.6.1 + IR 야간 shedding 가드 1줄(버전격리, v3.6.1 무손상 diff 1줄). Sonnet shedding 46건 ablation = **recovered 14/19(IR moving 오탐 전부)·broken 0/27(주간 허물 전부 유지)** → 78.2%→**85.1% 투영(=Fable 동급)**. **단일 실패모드를 프롬프트 1줄로 전부 회수** = 약한모델 끌어올리는 가장 싼 레버.

**종합 결론:** 입력표현(천장) 소진 → 천장 추가상승은 모델교체(Fable, +3.4%p p≈0.12)나 영상네이티브뿐. **바닥 올리기(약한모델→Fable)가 최선 ROI**(P3 룰 1줄 + P4 캐스케이드). 미세접촉·물·배변은 시각한계라 영상네이티브 대기.

**다음 — key-free (지금 가능, 우선순위 낮음):**
- [ ] **P5 다모델 합의** — 값나가는 버전(Gemini 교차투표)은 key-gated, Claude끼리는 P4가 "효과 미미" 답함 → key 복구 후 Gemini 묶음 권장.
- [ ] **P6 증거 레이어** — floor(배변·물) 우회 유일 레버지만 RF-DETR 탐지 파이프라인(반나절+탐지실패 리스크, OWLv2 47.5% 교훈) → `feature-rba-evidence-based-feeding-drinking.md` 본작업으로 승격 권장.

**다음 — key-blocked (Gemini key 복구 후, 🔬 1순위):**
- [ ] **P3 full-202 확정** — Sonnet v3.6.2 156건 배치 준비됨(`/tmp/p3_full_batches.json`, 이미 한 46건 재활용) + v3.5/3.6/3.6.1/**3.6.2** 202건 Gemini 정량회귀 **일괄**. 둘 다 통과해야 v3.6.2 DEFAULT 승격(현재 비-actionable라 묶어 대기).
- [ ] **⚠️ GT-noise 후보 2건 사람 영상 확인**: `5a34267c`·`ce9bab20` (GT=defecating 인데 v3.6.1+v3.6.2 독립 blind 둘 다 "주간 명확 허물 peeling"). blind=라벨QA → 자동정정 X, 사람 확인 후.

**상세:** 스펙 `experiment-weak-model-levers.md` (P1~P4 결과표 §4-1~4-4) · 메모리 `project_weak_model_lever_gap_diagnosis`

## 🆕 2026-06-09 (2차) — drinking 가설2 검증·GT 4건 정정·dataset-203 최신화

**완료 (커밋 `b5b039b`, push):**
- **drinking 가설2(시간축 licking 패턴) 검증 → 음성·보류**: motion PoC(global 프레임차분 `experiments/drinking-motion-poc/motion_energy.py`) + ffmpeg `deshake`(`compare_deshake.py`) 둘 다 음성. global motion은 미세행동(혀) 못 잡고, 얼굴핥기(chemoreception) micro가 drinking보다 높아 false positive. **운영 고정카메라 drinking 데이터 0건** 발견 → 검증 데이터 공백. (메모리 `project_drinking_temporal_poc_data_gap`, 스펙 `feature-rba-evidence-based-feeding-drinking.md` §14)
- **GT 4건 정정**: cam-motion drinking 4건(`05da625c`·`2420abd8`·`987c7b5d`·`ff1ecb03`) → 실제 moving(물 없는 곳 혀 날름 = chemoreception 경계, 사용자 영상 직접 확인). `_apply_gt_corrections.py` 2차 — **로컬(파일명+manifest) 적용 완료, ⚠️DB(`behavior_logs`) 미적용 — key 복구 시 SQL UPDATE 4건 필수**(회귀평가 SOT가 DB). drinking 20→16.
- **drinking 8건 완화 = 개별프레임 5/8 회복** (기존 frames blind 재활용으로 검증). 몽타주 입력이 진범(흔들림/시간축 아님). 남은 3건(`f4b33f32`·`7124cebe`·`cf698b78`)=최흐림/확대 → 영상네이티브(Gemini)/HITL.
- **YOLO 라이선스 확정**: Ultralytics AGPL-3.0(SaaS도 소스공개 의무=독약) 회피 → **RF-DETR/YOLOX/D-FINE(Apache 2.0)**. GPL(v7/9)은 서버사이드 OK·온디바이스 임베드(자체HW캠) 시 터짐. YOLO 스펙 작성 시 라이선스 섹션에 그대로 사용.
- **rba-worker 역할 정리**: self-hosted R&D/배치/specialist 워커(전면 대체 아님 — local LLM 실측상 shedding specialist + Gemini hybrid). YOLO custom 학습 실행 위치.
- **dataset-203 README 전문가송부용 최신화**: GT 분포(moving 72/drinking 16) + 누적정정 17건 + Timeline drinking 재정정 행 + 블로커 "계정 플래그"→"Google 전역 AQ. 이슈" 정정. (storage gitignore라 git 미추적 — 폴더 직접 송부)

**미완 — key-free (지금 가능):**
- [x] **약한 모델 레버 테스트 (2026-06-10/11)** → **위 2026-06-10/11 섹션으로 이동.** P1~P4 완료(천장 소진/바닥 회수), P5/P6 보류.
- [x] **frames 79.7% 재계산** — 정정 GT 재채점 **81.7%**(165/202). Fable 5 동조건 85.1% (`_score_frames_fable5.py`).
- [ ] **C-2 라벨링 OOD UX 브라우저 검증** (코드 완료, 사용자 직접).
- [ ] **`5936`·`5cfe1d48` GT 재검토** (2026-06-08 성급한 hf 정정 의심 — manifest 갱신).

**미완 — key-blocked (Gemini key 복구 후):**
- [ ] **DB GT 정정 4건 SQL sync** (cam-motion drinking 4건 → moving). 회귀평가 SOT가 DB라 평가 전 필수.
- [ ] **Gemini 회귀평가**: v3.5/v3.6/v3.6.1 202건 정량 (`eval_vlm_v36_handfeeding.py --version v3.6|v3.6.1` 분기 **이미 적용됨**, 커밋 `0cad564`). P0 floor + OOD recall.
- [ ] **fly.io VLM 워커 key 점검** (같은 계정이면 production inference 중단 중).
- [ ] **defecating/drinking 영상 트랙 재측정** (Gemini 영상이 frames 이기나).
- [ ] **운영 고정카메라 drinking 데이터 수집** (가설2 재개 전제 — 스펙 §7 Phase 7 passive 녹화).
- 근본해결: **Vertex AI 인증 전환**(AQ. key 우회, 미결정 — 메모리 `feedback_gemini_aq_key_account_flag`).

**상세:** 메모리 `project_drinking_temporal_poc_data_gap` · 스펙 `feature-rba-evidence-based-feeding-drinking.md` §14

---

## 🆕 2026-06-09 — frames 입력 실험 + 평가셋 202확정 + hiding 폐기 + dataset-203 핸드오프

**완료 (커밋 `867e978`, push):**
- **★ frames 입력 표현 실험 (핵심 발견)**: 같은 모델(Claude)·프롬프트(v3.6.1)로 **평가 입력만** contact-sheet 몽타주(~72px/프레임) → 개별 풀해상도 프레임(1024px)로 교체. **미세접촉 63건 46%→67%(+21%p).** 전체 202건 Claude subagent blind = **raw 79.7%** (hand_feeding 96·moving 93·shedding 90·paste 82·prey 73·drinking 55·defecating 19·unseen 50).
  - **결론 — 입력 표현이 정확도 1순위 레버**(프롬프트 아님). 153건 72.5%는 몽타주가 입력을 뭉갠 과소평가였음 → production(Gemini 영상)은 더 높을 것, key 복구 후 **재측정 1순위**.
  - **★ shedding 반전**: "정지프레임=시간축행동 0" 추정 틀림 — 허물 패치는 정적 시각증거라 90%. (사전 추정 65% → 실측 79.7%). 진짜 바닥 = defecating 19%(순간)·drinking 55%(벽 응결수). (메모리 `feedback_frames_beat_montage`)
- **GT 정정 batch + hiding 폐기**: 사람급여 오라벨 7건(→hand_feeding/moving) + **hiding 클래스 폐기** 3건(→moving, 모델도 moving 확인) + 편집영상 1건 삭제 → **평가셋 203→202건**. manifest.csv + `behavior_logs` DB(7 UPDATE+1 DELETE) sync. ⚠️ `036a650d`는 정지프레임서 시린지로 오판→실제 게코혀(drinking 유지) — **확정은 사람 영상** 원칙 실증.
- **defecating/drinking 전략 수립** (메모리 `project_defecating_drinking_strategy`): defecating=순간이벤트→영상네이티브/before-after, drinking=벽응결수(물안보임)→메타(분무 타임스탬프)/HITL/GT정제. **둘 다 프롬프트로 못 풂.**
- **dataset-203 VLM 전문가 핸드오프** (`storage/dataset-203/`, gitignore 로컬): README.md(히스토리/한계/비용) + analyze.py(gemini/contact-sheet/frames 3방식 재현) + _production_code/. 사용자가 zip 떠서 발송 예정.

**⚠️ 계속 차단 — Gemini key:** 영상 트랙 정량 불가. 복구 후: **defecating/drinking 영상 재측정(frames 이기나)** → v3.6.1 203건→202건 정량 회귀. ⚠️ **fly.io VLM 워커도 같은 key면 production inference 중단 중** — key 교체 시 fly secret 점검.

**팔로업:** `5936`·`5cfe1d48` GT 재검토 / `eval_vlm_v36_handfeeding.py` v3.6.1 분기 추가(key 전 선행 가능) / C-2 라벨링 OOD UX 브라우저 검증 / frames 79.7% 교차검증(자기검증이라 인용 주의).

**상세:** `storage/dataset-203/README.md` · 메모리 `feedback_frames_beat_montage`·`project_defecating_drinking_strategy`

---

## 🆕 2026-06-08 — Claude 트랙 203 평가 + v3.6.1 OOD 초안 + dataset-203 + YOLO 계획

**완료 (커밋 `8fca779`·`1af0eff`·`de2de48`·`6b7d1c4`, push):**
- **eval-0608 44건 신규 evidence셋** R2(`clips/eval-0608/`)+DB 등록 + **평가셋 159 동결 → 203 통합** (사용자 결정). `load_eval_set`=203 / `load_eval_set_0608`=44, 159=203−44 복원가능. (메모리 `project_eval0608_evidence_set`)
- **Claude 구독 트랙 203 적합 153건 blind 평가** (contact sheet, GT 미공개 서브에이전트). 미세행동 50건은 contact sheet 불가로 제외:
  - **적합도 맵**: moving 91%·hand_feeding 88% 가능 / drinking 35%·eating_prey 40%·eating_paste 61% 미세접촉 한계 / shedding(6x6 3회로도 20%)·defecating(0%)·hiding·unseen 완전불가 → **Gemini 영상 필요 영역 확정**.
  - raw v3.6 71.2% → **v3.6.1 72.5%** (과발동 수정 −6 / recall 손실 +4 상쇄). (메모리 `project_contact_sheet_adequacy_v361`)
- **GT 오류 9건 정정 (blind=라벨 QA)**: `2961`(hf→paste) + 159건 8건(eating_prey/paste→hf, 사람이 핀셋/시린지/스푼 급여하는 영상인데 v3.5 시절 라벨). 8장 육안 교차검증 후 정정.
- **v3.6.1 OOD 룰 초안** (`web/prompts/backups/system_base.v3.6.1.md`, `prompt_version="v3.6.1"` 격리, v3.6 무손상): OOD "손/도구 보이면 hf" → **"음식 전달 행위"로 좁힘**. 정성 11건 과발동 5/5 수정 + recall 6/6 유지. **⚠️ 채택 절대 보류 — 회귀(Gemini) 없이 `DEFAULT_PROMPT_VERSION` 승격 X.**
- **dataset-203** `storage/dataset-203/` (gitignore, 로컬 2.2GB): 203건을 `{GT}__{Claude v3.6.1}__{clip8}.{ext}` + `manifest.csv`. 파일명만으로 GT vs Claude 일치/불일치 검수. 중복 영상 142개 휴지통.

**⚠️ 여전히 차단 — Gemini key:** v3.6.1 정량 + production 승격의 **단일 블로커**. AQ. prefix 계정 플래그(`feedback_gemini_aq_key_account_flag`). 표준 AIza key 확보 후: `eval_vlm_v36_handfeeding`에 `prompt_version` 분기 추가 → 203으로 **v3.5/v3.6/v3.6.1 정량 비교** (P0 floor + OOD recall + 과발동 감소).

**사용자 방향 (2026-06-08):**
- **v3.5 영구 폐기 결정** — hand_feeding 필요하니 앞으로 **v3.6+**(hand_feeding 포함). 단 DEFAULT 승격은 Gemini 회귀 통과 후. v3.5가 세운 floor(P0 85.5%)는 **품질 바닥선으로 유효**(프롬프트는 버리되 기준은 유지).
- **YOLO 계획 (재정의)**: "moving 거르기"가 아니라 **YOLO = 이벤트 단서 객체 검출(그릇/손/도구/prey/허물) → VLM 라우팅 + evidence**. 효과 = 비용절감(moving 31% 스킵, 확실) + 정확도(evidence-aug, 간접). 미세행동 병목은 YOLO 밖(영상 시간축/Gemini full/HITL). **dataset-203이 게코 fine-tune YOLO 학습 데이터로 적합**(OWLv2 47.5% 검출실패 교훈). → `project_yolo_evidence_layer_status` 메모리 + `docs/AI-VIDEO-ANALYSIS-STRATEGY.md`.

**팔로업:** `5936`·`5cfe1d48` GT 재검토(성급한 hf 정정 의심 — manifest도 갱신) / Gemini key 확보 → v3.6.1 정량 / YOLO 트랙 스펙화.

**상세:** `experiment-claude-subscription-rba.md` · `experiments/eval-159-claude/REPORT.md`

---

## 🆕 hand_feeding OOD 트랙 + YOLO 다음 트랙 (2026-06-07)

**완료 (커밋 `676dfd4` + `0e1f7bc`, push):**
- C-1 hand_feeding 라벨 5곳 (types.ts / labelingApi.ts / labeling page / prompts.py / labels.py) — tsc 0, pytest 64
- C-2 라벨링 OOD 안내 UX (코드 완료, **브라우저 검증 대기**)
- C-3 v3.6 후보 프롬프트 + `build_system_prompt(species, *, prompt_version)` 버전 격리 (v3.5 production 9-class 보존, v3.6=10-class)
- GT 정정 6건 Supabase `behavior_logs(human)` sync (5→hand_feeding, 1→moving) + audit
- 159건 오답 진단 (`scripts/diagnose_vlm_errors.py`): feeding-merged 81.8% (GT sync로 6건 오답 재분류된 효과 — **v3.5 저하 아님**), 최대 혼동 moving↔feeding 13건

**⚠️ 차단됨 — key 확보 후 즉시:**
- v3.6 회귀평가: Gemini **AQ. prefix key 계정 플래그**로 막힘 (크레딧 소진 아님). 다른 Google 계정 AIza key or Google manual review. 재개: `rm /tmp/vlm-regression-v36.jsonl && PYTHONPATH=. uv run python scripts/eval_vlm_v36_handfeeding.py`. **fly worker key도 점검** (같은 플래그 계정이면 production VLM도 멈춤).

**진단이 준 다음 전략:**
- defecating(69%) / eating_paste(5건) / drinking = **영상 추가 가치** / 그릇↔먹기 혼동 = **시각 한계**(영상 무의미, ROI/UX/YOLO로) / hand_feeding = **v3.6가 풀 듯**(Gemini reasoning에 도구 이미 인지)

**YOLO evidence layer = 다음 트랙 (사용자 트리거 대기):**
- 사용자가 ①운영환경 게코 영상 ②게코 frame ③YOLO 공부 진행 후 **"YOLO 하자"로 트리거**. 그때 `specs/experiment-yolo-evidence-layer.md` 스펙 → **Phase 3(pretrained 검출 한계 확인) 먼저**, custom(Phase 4-5)은 나중. 실행은 rba-worker 영역 검토. 로드맵: `docs/learning/yolo-video-analysis-study-plan.md`. **YOLO = 좌표·시간 evidence 생성**(행동 판단 X). OWLv2 47.5% 검출 실패 교훈(`experiment-tracking-vlm-input.md` 폐기).

**팔로업:** C-2 브라우저 검증 / rba-worker `BEHAVIOR_CLASSES` cherry-pick(10-class sync) / `feature-vlm-worker-cloud` 회귀 재측정(아래 80.5%는 GT sync 전 수치) / 스펙: `feature-hand-feeding-ood-label.md`

---

## 🆕 Cloud Migration 트랙 시작 (2026-05-07)

사용자 명시 — 기존 모놀리식 FastAPI 를 분산 워커 + BaaS 패턴으로 전환. spec 4개 작성 완료, 코드 작업 시작 대기.

| 영역 | 상태 | 위치 |
|---|---|---|
| 상위 로드맵 + 결정 락인 8개 | ✅ spec 작성 | [`cloud-migration-roadmap.md`](cloud-migration-roadmap.md) |
| capture worker 분리 (`backend.main` lifespan → 별도 entrypoint) | 🚧 **코드 완료, 실기 검증 대기** (2026-05-07) | [`feature-capture-worker-extraction.md`](feature-capture-worker-extraction.md) |
| VLM worker production (PoC → 자동 폴링) | 🚧 **1건 검증 완료, 회귀 미해결** (2026-05-07) — UNIQUE+RPC 마이그레이션 + 1건 inference (moving 0.90, GT 일치). 159건 회귀 80.5% (floor 85.5% 미달) — production 진입 전 해결 필수. | [`feature-vlm-worker-cloud.md`](feature-vlm-worker-cloud.md) |
| VLM worker fly.io 배포 (always-on 클라우드) | ✅ **완료 2026-05-07 (후속)** — `petcam-vlm-worker` nrt, shared-cpu-1x 256MB. E2E 검증 완료. `.dockerignore` web prompts SOT 충돌 회고 기록. | [`feature-vlm-worker-fly-deploy.md`](feature-vlm-worker-fly-deploy.md) |
| 라벨링 웹 백엔드 분리 (Vercel→Supabase/R2 직결) | ✅ **완료 2026-05-07 (후속2)** — owner 검수 4 endpoint Vercel 직결. `label.tera-ai.uk` 맥북 의존 0. clip 3b0d9995 실기 검증. | [`feature-labeling-web-cloud.md`](feature-labeling-web-cloud.md) |
| API 서버 fly.io 이전 + Flutter contract endpoint 2개 | ✅ **완료 2026-05-08 — Phase 1+2+3+4 모두 종료.** `api.tera-ai.uk` 가 fly.io edge (66.241.124.67) 직결 + Let's Encrypt E8 cert (2026-08-06). 사용자 맥북 의존 0 (capture_main 제외). DEPLOYMENT.md / ARCHITECTURE.md 갱신 완료. | [`feature-api-server-fly-deploy.md`](feature-api-server-fly-deploy.md) |
| Flutter 라벨 chip + 하이라이트 탭 + R2 signed URL | 🚧 **백엔드 측 endpoint 채움 완료 2026-05-08** — Flutter 측 작업 대기. Flutter 측 새 세션에 `docs/handoff-prompts/flutter-cloud-migration.md` 던지면 됨. | [`flutter-cloud-handoff.md`](flutter-cloud-handoff.md) |
| Flutter 레포에 던질 handoff prompt | ✅ 작성 | [`../docs/handoff-prompts/flutter-cloud-migration.md`](../docs/handoff-prompts/flutter-cloud-migration.md) |
| 학습 자료 (사용자가 다른 에이전트와 공부용) | ✅ 작성 (이전 세션) | [`../docs/learning/cloud-architecture-overview-learning.md`](../docs/learning/cloud-architecture-overview-learning.md) |

**시나리오 매트릭스 (Flutter 측):**
- A. 자동 라벨 보기 = 모든 유저
- B. 라벨 수정 (HITL) = **labelers 멤버 (admin/staff) 만**, **라벨링 웹** 에서 (Flutter 안 만듦)
- C. 하이라이트 = `behavior_logs.action ∉ {moving, unknown}` 클립 (모든 유저 본인 거)

**핵심 결정 (재논의 금지):** §4-1 Supabase 유지, §4-2 R2 직접, §4-3 capture 모듈 분리, §4-4 DB-as-message-bus, §4-5 labelers=admin, §4-6 라벨 수정 UI 분리, §4-7 하이라이트 정의, §4-8 behavior_logs source='vlm'.



## 🛑 백엔드 캡처 일시 중지 중 (2026-05-05) — 캡처 워커 한정

**상태:**
- `backend.main:app` (uvicorn) — **fly.io `petcam-api` production 가동 중 (2026-05-08 cutover 완료).** `api.tera-ai.uk` 직결, always-on. 사용자 맥북 의존 0.
- `backend.capture_main` — **여전히 일시 중지.** 사용자 맥북 로컬에서만 가동 가능 (RTSP LAN 의존). 사용자 명시 신호 받기 전 자동 재개 X.

**왜 (캡처 워커):** 클립 정리 작업 중 새 클립이 계속 들어오는 걸 막기 위함. 사용자 명시 지시
(2026-05-05): "캡쳐를 모두 일시중지 시켜. 내가 재개할 때 까지 일시정지 하고."

**캡처 워커 재개 방법:**
```bash
cd /Users/baek/petcam-lab && uv run python -m backend.capture_main
```

**재개 전제 조건:** 사용자가 직접 "캡처 재개해" 라고 말할 때만. AI 가 자체 판단으로
재개하지 말 것. 정리 작업 끝나도 자동 재개 X.

## ✅ 직전 세션 산출 — motion 풀 backfill 완료 + owner-override 권한

백엔드 EncodeUploadWorker + R2 업로드 + DB sync 일관 동작 확인. 두 단계 backfill 완료:
- **1차** (camera_id NOT NULL): motion 232/232, 평균 압축 44.5%, 0 fail
- **2차** (NULL 88 PoC 업로드, `clips/uploaded/...` literal): 88/88, 157s, 0 fail (사용자 결정 (b))

**최종 R2 상태**: motion total 382, in_r2 382, pending 0. 88건은 `clips/uploaded/{date}/{stem}_{id}.mp4`.

추가로 **owner-override 라벨 권한** 구현 — `POST /clips/{id}/labels` body 에 `labeled_by` 필드 (선택). owner 가 다른 라벨러 라벨을 강제 수정/생성 가능 (관리자/테스터 검수용). labeler 멤버는 본인 라벨만. 19 테스트 통과.

다음은 사용자 브라우저 E2E (로그인 → 큐 → 클립 → R2 영상 재생) + (통과 시) Vercel 배포.

| 영역 | 상태 |
|---|---|
| §3-1 R2 인프라 (`backend/r2_uploader.py`, env, RLS) | ✅ 코드 완료 |
| §3-2 인코딩 파이프라인 (`backend/encoding.py`, `encode_upload_worker.py`) | ✅ 코드 완료 |
| §3-3 업로드 워커 + DB sync (`backend/r2_uploader.py` insert) | ✅ 코드 완료 |
| §3-4 실기 검증 (motion 382/382 backfill — 232 cam + 88 PoC + 62 신규) | ✅ 2026-05-02 |
| §3-5 `/clips` API r2 redirect (302) + 라벨링 웹용 `/file/url` JSON | ✅ 코드 완료 |
| §3-6 Label API (`backend/routers/labels.py`, `behavior_labels` 테이블) | ✅ 코드 완료 |
| §3-7 라벨링 웹 (`web/src/app/labeling/`) | ✅ 코드 완료 |
| §3-7 Vercel 배포 + Cloudflare DNS (`label.tera-ai.uk`) | 🟡 사용자 작업 |
| §3-7 라벨러 부트스트랩 SQL (`auth.users + labelers INSERT`) | 🟡 사용자 작업 |
| §3-7 라벨러 모바일/PC 실기 검증 | 🟡 사용자 작업 |

상세: [feature-r2-storage-encoding-labeling.md](feature-r2-storage-encoding-labeling.md)

## 🔒 락인된 결정 — 새 세션에서 재논의 금지

### RBA / VLM (Round 3 종료, 2026-04-30 락인)

- 공식 기술명: **RBA (Reptile Behavior Analysis)** — 밤사이 파충류 펫캠 영상을 행동 타임라인과 케어 시그널로 바꾸는 AI 분석 시스템.
- RBA Track A = Zero-shot VLM 운영 기준선. RBA Track B = SegmentVLM 정밀 분석/실험 트랙.
- 사업·관계도 설명 SOT: [`docs/AI-VIDEO-ANALYSIS-STRATEGY.md`](../docs/AI-VIDEO-ANALYSIS-STRATEGY.md).
- **v3.5 production floor = 85.5%** (159건 feeding-merged 기준 — **202건으로 재측정 필요**) / 85.7% (154건 dish-postfilter 기준)
- **⚠️ 2026-06-08 변경**: 평가셋 159 → **203 통합**(eval-0608 44). **⚠️ 2026-06-09**: GT 정정 + **hiding 클래스 폐기**(모션 트리거 카메라에 0% 구조적 한계) + 편집영상 삭제 → **203→202건 확정**. 사용자 **v3.5 프롬프트 영구폐기**(hand_feeding 필요 → v3.6+). 단 **v3.5 floor(P0 85.5%)는 품질 바닥선으로 유효** — v3.6+가 202건 기준으로 넘어야 함. DEFAULT 승격은 Gemini 회귀 후. (메모리 `project_vlm_v35_baseline_lock`)
- 사용자 명시: "이거보다 더 나빠져서는 안 됨." → 어떤 변경이든 floor 미달이면 채택 X
- v3.5 prompt 백업: `web/prompts/backups/{system_base,crested_gecko}.v3.5.md` — 회귀 시 즉시 롤백
- **prompt 변경 시도 자체가 ROI 0** (6회 검증 실패: v3.6/v3.7-B/v4 + Track B/C/D/E + dish-postfilter)
- 잔존 오답은 prompt 한계가 아닌 **시각 한계** → UX/메타데이터/HITL 정공법
- 회귀 가드 의무: 159건 동일 평가셋으로 새 변경 측정 → 85.5% 미달이면 채택 X

### UX 통합 (2026-05-02 완료)
- `feature-vlm-feeding-merge-ux` ✅ 완료 — `types.ts toFeedingMerged()` + `UI_BEHAVIOR_CLASSES` (8 클래스 노출, raw 9 보존)
- F3 결과/평가 매핑 동치 9/9 통과, tsc 통과
- 9 raw → 8 UI: drinking + eating_paste → feeding 묶음

### HITL ping (2026-05-02 신규 spec)
- `feature-vlm-hitl-ping` 🚧 — defecating/shedding/eating_prey 모호 케이스 사용자 검수 (일일 5건 + opt-in)
- confidence<0.7 또는 confusion-prone 클래스 트리거. 코드 미착수.

## 🧭 다음 세션 즉시 착수 — 라벨링 웹 로컬 E2E → NULL 88 결정 → Vercel 배포

**A. R2 가동 검증 ✅ 2026-05-02** (motion 232/232 backfill로 갈음 — spec §3-4 [x]).

### B1. 라벨링 웹 로컬 E2E (트랙 A — 백엔드 일시 중지 상태에서는 보류)

> ⚠️ 2026-05-07 기준: 백엔드 (capture/API) 일시 중지 상태 (위 🛑 섹션). 트랙 A 재개하려면
> 사용자 명시 신호 후 `uv run uvicorn backend.main:app` + `uv run python -m backend.capture_main`
> 부팅 → 라벨링 웹 dev server `:3001` 재기동 → 아래 검증.

- 사용자 브라우저 검증:
  1. `http://localhost:3001/labeling` → `/labeling/login` 자동 redirect
  2. Supabase 계정 로그인 (owner: `bss.rol20@...` 등)
  3. `/labeling` 큐에 본인 클립 표시 (owner는 본인 user_id 클립만; 라벨러면 전체)
  4. 클립 클릭 → `/labeling/{clipId}` → 영상 재생 (R2 signed URL) + 썸네일 표시
  5. 라벨 폼 제출 → DB `behavior_labels` row 생성 확인
- 옛 PID 참조 (PID 68928, background task `b8xejq7hy`) 는 2026-05-02 세션 시점 기록. 2026-05-05 backend 중지 후 무효.

### B2. ✅ NULL camera_id 88건 결정 (b 채택) — 2026-05-02

PoC 평가셋(crested_gecko Round 1~3)을 `clips/uploaded/{date}/{stem}_{id}.mp4` literal 로 backfill.
- 사용자 명시: "싹다 업로드하고 관리자&테스터가 라벨을 확인/수정 할 수 있어야 해 b로 가."
- 88/88 succ, 157s. R2 키에 `uploaded` 박혀 카메라 캡처와 attribution 분리 가능.
- 후속: **owner-override 라벨 권한** 추가 (labels.py LabelCreate.labeled_by). owner 만 다른 라벨러 라벨 강제 수정 가능.

### B3. 라벨링 웹 Vercel 배포 (B1 통과 후)

- Vercel (`web/` 디렉토리) — env 3개 (`NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY` = `eyJ...rgtvY`, `NEXT_PUBLIC_BACKEND_URL=https://api.tera-ai.uk`)
- Cloudflare DNS — `label.tera-ai.uk` CNAME → `cname.vercel-dns.com`
- 백엔드 `.env` 에 `LABELING_WEB_ORIGINS=https://label.tera-ai.uk` 추가 + 서버 재기동
- 라벨러 1명 부트스트랩 SQL ([docs/DEPLOYMENT.md "라벨링 웹 (Vercel)"](../docs/DEPLOYMENT.md))
- 라벨러 모바일/PC 양쪽에서 클립 10건 라벨 → `behavior_labels` row 10개 확인

### 후순위 (A/B 끝난 뒤 사용자 결정)

- **HITL ping 구현** — spec [`feature-vlm-hitl-ping.md`](feature-vlm-hitl-ping.md). 라벨링 웹 인프라 재사용 (같은 `behavior_labels` 테이블) 검토
- **메타데이터 보강** — dish detection / before-after / 시간대 / 카메라 ROI prior. prompt에 박지 말 것 (룰 5 회피) — 별도 분류기/후처리 레이어로
- **Stage E 온디바이스 필터링** — 별도 트랙. SOT (`../tera-ai-product-master/docs/specs/petcam-b2c.md`) 먼저 읽고 spec 킥오프

## 🗂️ 현재 시스템 상태 스냅샷 (2026-05-08)

- **VLM:** Gemini 2.5 Flash + v3.5 prompt = production 락인 floor 85.5%(159). **2026-06-08: 평가셋 159→203 통합 + v3.6.1 OOD 초안(`system_base.v3.6.1.md`, 채택보류). Claude contact sheet 정성 v3.6 71.2%→v3.6.1 72.5%(153 적합). GT 9건 정정. 정량은 Gemini key 복구 후.** v3.5 영구폐기 방향(v3.6+ 전환, 회귀 후 DEFAULT 승격).
- **R2:** ✅ 인프라 가동 + motion 382/382 backfill (232 cam + 88 PoC `clips/uploaded/` + 62 신규)
- **라벨 권한:** ✅ owner-override 추가
- **라벨링 웹 (#4 외부):** ✅ **`label.tera-ai.uk` Vercel always-on 가동 중**. owner 검수 4 endpoint Vercel→Supabase/R2 직결 (2026-05-07 후속2). 라벨러 큐 (`/labels/queue`, `/labels/mine`) 만 BACKEND_URL 의존
- **API 서버 (#1):** ✅ **fly.io `petcam-api` production 가동 중** (2026-05-08 cutover 완료). nrt, shared-cpu-1x 256MB, always-on, `min_machines_running = 1`. `api.tera-ai.uk` (fly.io edge 66.241.124.67) HTTPS 200, Let's Encrypt E8 cert (2026-08-06). 사용자 맥북 cloudflared / uvicorn 의존 0. Phase 1 endpoint 2개 (`/me/is_labeler`, `/clips/highlights`) 가동.
- **캡처 워커 (#2):** `backend.capture_main` — 코드 완료, 일시 중지 (2026-05-05). 사용자 명시 신호 받기 전까지 자동 재개 X. RTSP LAN 의존이라 fly.io 이전 대상 X
- **VLM 워커 (#3):** ✅ **fly.io `petcam-vlm-worker` always-on 가동 중** (2026-05-07). nrt, shared-cpu-1x 256MB. clip 70093109 1건 E2E 검증 통과 (action=moving 0.9). 159건 회귀 가드 + 100건 비용 추적 미해결.
- **Auth:** `AUTH_MODE=prod`, Supabase JWT (ES256). CORS 라벨링 웹 origins 분리
- **카메라:** cam1 (1c1aea9f) / cam2 (3a6cffbf) — 오너 bss.rol20. mirror cam1-mirror / cam2-mirror — QA dlqudan12
- **Tests:** 247 passing (이전 239 + Phase 1 신규 8 — `/me/is_labeler` 2 + `/clips/highlights` 6)
- **마이그레이션 적용:** 2026-05-07 — `behavior_logs` UNIQUE(clip_id, source) + RPC `fn_vlm_pending_clips`
- **Stage:** A~D5 ✅ / E 🆕 (스코프 미확정) / VLM PoC ✅ Round 3 종료 / R2 ✅ 가동 + 라벨링 코드 완료 / **Cloud Migration 트랙: capture 코드 완료 + VLM fly.io ✅ + 라벨링 웹 ✅ + API 서버 fly.io ✅ (cutover 완료) + Flutter 측 미착수**

## 📂 맥락 복원 — 읽을 파일 (우선순위)

새 세션이 맥락 없이 들어왔을 때 이 순서로:

1. **이 파일** — 오늘의 시작 지점 + 락인 결정
2. [feature-r2-storage-encoding-labeling.md](feature-r2-storage-encoding-labeling.md) — R2/라벨링 전체 결정 + 사용자 가동 체크리스트
3. [feature-poc-vlm-web.md](feature-poc-vlm-web.md) — VLM PoC 전체 결정 이력 (Round 1~3, §3-13까지)
4. [feature-vlm-feeding-merge-ux.md](feature-vlm-feeding-merge-ux.md) — UX 통합 완료 (raw 보존 + UI 매핑)
5. [feature-vlm-hitl-ping.md](feature-vlm-hitl-ping.md) — HITL spec (코드 미착수)
6. `~/.claude/projects/-Users-baek-petcam-lab/memory/MEMORY.md` — 자동 메모리 인덱스
7. [../README.md](../README.md) — 1분 요약 + 퀵스타트
8. [../docs/ENV.md](../docs/ENV.md) — R2 + CORS 환경변수
9. [../docs/DEPLOYMENT.md](../docs/DEPLOYMENT.md) — R2 + Vercel + 부트스트랩 SQL
10. [README.md](README.md) — spec 운영 규칙 + 전체 스펙 목록

## 💬 사용자가 "뭐부터 해야해?" 물으면

1. **첫 확인 — 락인 존중**: v3.5 baseline은 건드리지 않는다고 인지. prompt 변경/clean slate 제안 금지.
2. **즉시 액션 — Flutter 세션에 cutover 완료 신호 + 라벨 chip / 하이라이트 탭 구현**:
   - 백엔드 측 Cloud Migration 다 끝남 (2026-05-08 fly.io cutover). 옆 레포 (`/Users/baek/myProjects/tera-ai-flutter`) 에서 새 세션 띄우고 `docs/handoff-prompts/flutter-cloud-migration.md` 그대로 prompt 로 던져.
   - Flutter 5단계 PR (handoff §5): 도메인 모델 → fileUrl async → 라벨 chip → 하이라이트 탭 → labeler deep link.
3. **트랙 진행 상태** (Cloud Migration):
   - **B1. capture worker 분리** ([`feature-capture-worker-extraction.md`](feature-capture-worker-extraction.md)) — 2026-05-07 코드 완료. 자체 HW 카메라 도착 전까지는 사용자 맥북에서 `uv run python -m backend.capture_main` 으로 가동 (현재 일시 중지). **재개는 사용자 명시 신호 후.**
   - **B2. VLM production 워커** ([`feature-vlm-worker-cloud.md`](feature-vlm-worker-cloud.md)) — 코드 + fly.io 가동 완료. **남은 일:** 159건 회귀 (80.5% / floor 85.5%) + 100건 비용 추적 (별도 트랙).
   - **B2.1. VLM fly.io 배포** ([`feature-vlm-worker-fly-deploy.md`](feature-vlm-worker-fly-deploy.md)) — ✅ 2026-05-07 완료.
   - **B2.2. 라벨링 웹 백엔드 분리** ([`feature-labeling-web-cloud.md`](feature-labeling-web-cloud.md)) — ✅ 2026-05-07 완료.
   - **B2.3. API 서버 fly.io 이전 + Flutter contract endpoint** ([`feature-api-server-fly-deploy.md`](feature-api-server-fly-deploy.md)) — ✅ **완료 2026-05-08 (Phase 1+2+3+4 종료, cutover 후 production traffic 정상).**
   - **B3. Flutter 측 작업** — 별도 레포 (`/Users/baek/myProjects/tera-ai-flutter`). handoff prompt (`docs/handoff-prompts/flutter-cloud-migration.md`) 그대로 새 세션에 던지면 됨. **백엔드 측 cutover 끝남 (2026-05-08)** → production 도메인 (`api.tera-ai.uk`) 그대로 사용 가능.
4. **회귀 가드 자동 적용**: 어떤 변경이든 85.5% floor 검증 의무 (VLM 워커 변경 시).
