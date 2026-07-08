# v4.1 shedding IR-guard 회귀 보고서 (Report)

> 규칙: [`.claude/rules/research-testing.md`](../../.claude/rules/research-testing.md).

**실험 ID:** v41-shedding-ir-guard · **phase:** v4.1 · **날짜:** 2026-07-08 · **상태:** ✅ 실행 완료 · **decision: `reject`**
**시험지:** [`TEST-SHEET.md`](TEST-SHEET.md) · **관련:** next-session 07-08 팔로업 3 · 메모리 `gecko-morph-shedding-false-positive`·`nightly-classify-nondeterministic-temperature`·`nightly-shedding-fp-is-nondeterminism`

## 1. 무엇을 측정했나 (시험지 요약)

| 축 | 값 |
|---|---|
| 가설 H1 | v4.1(shedding 근거를 창백색→물리적 분리 이동 + IR 가드)이 production 흰모프 IR shedding 오탐을 억제하면서 진짜 탈피·급여경계 유지 |
| Set-FP | 32건 (nightly VLM=shedding·사람 GT=moving, production camera) — "does it fix?" |
| Set-REG | 185 동결셋 (v4.0 캐시 재사용) — "does it break?" |
| 모델/입력 | Claude Sonnet 4.6 blind · 적응형 frames@1080 · v4.0 vs v4.1 |
| 게이트 | Part A 억제율≥60%+broken=0+new-err≤2 / Part B broken_shed≤2+급여 rec≥brk+raw≥−3%p |

## 2. 결과

**배치:** Workflow blind 서브에이전트 32배치 · 4.79M 토큰 · 2490 tool_use · ~20분 · 채점 `_score.py`.

### ⚠️ 시험지 대비 — 전제 붕괴 + harness 버그 (사후변경 아님, 실행 중 발생)

1. **Set-FP 전제 붕괴 (핵심):** 시험지는 "v4.0가 이 32건에 shedding 오탐을 낸다"를 전제했으나, **adaptive@1080에서 v4.0·v4.1 두 프롬프트 모두 32건 전부 `moving`** 으로 정답 판정. shedding 예측 **0/64** (v4.0 32 + v4.1 32 배치 전체, 아래 harness 스크램블 포함해도 불변). → **오탐이 재현되지 않음** = 억제할 대상 자체가 없음(S0=0).
2. **harness 버그:** blind 인퍼런스에서 에이전트가 공유 `/tmp/beval/tasks.json`의 **자기 배치 인덱스를 오독** → 5개 배치(fp_v41 3개·reg_v41 2개)가 다른 배치의 sid 반환(스크램블). v4.0-vs-v4.1 **차이**와 **Part B 회귀(185)** 는 오염 → **무효 처리**(채점기가 출력한 raw −4.3%p·broken_shed 2는 결측을 오답 처리한 **아티팩트**, 실측 아님).

### 살아남는 견고한 결과 (버그·스크램블 무관 — 두 프롬프트 만장일치라서)

| 지표 | 값 | 신뢰도 |
|---|---|---|
| Set-FP 예측 분포 (v4.0+v4.1 전체 64건) | **moving 64 / shedding 0** | 🔒 확정 |
| nightly shedding 오탐 재현 여부 @adaptive@1080 | **재현 안 됨** | 🔒 확정 |
| nightly 입력표현 vs 랩 | `extract_adaptive` **identical** (코드 동치, interval3.5/clamp6~20/1080/구간중앙/ffmpeg-ss) | 🔒 확정 (소스 대조) |
| v4.1 진짜 탈피 억제? | reg 배치서 shedding 여전히 25회 발화 → 과억제 아님 | ✅ (reg 대부분 clean) |

## 3. 분석

- **가설 판정: H1 검증 불가 / H0 유지.** v4.1이 억제할 오탐이 이 입력표현에서 존재하지 않음 → 프롬프트 효과를 측정할 표면이 없음.
- **근본원인 = temperature 비결정성 (입력·프롬프트 아님):**
  - nightly와 랩의 프레임 추출이 **바이트 동치**(소스 대조 확인) → 입력표현 배제.
  - nightly `classify.py` 는 `claude -p` headless 로 temperature 미제어 (메모리 `nightly-classify-nondeterministic-temperature` 이미 문서화). 흰/창백 IR 모프(트라이익스트림 할리퀸)가 shedding을 **그럴듯한 stochastic 오답**으로 만들고, 비결정 샘플링이 가끔 그걸 뽑음. nightly는 그 misfire들을 포착, 랩 재추론은 전부 moving.
  - 즉 오탐 = **간헐적 노이즈**(흰모프가 확률을 높임), **체계적 프롬프트 실패 아님.** 레포 학습 "입력표현이 레버, 프롬프트 아님"과 정합하되, 여기선 입력마저 동일 → 남는 변수는 샘플링 비결정성뿐.
- **v4.1 프롬프트 자체는 무해**(reg서 shedding 25회 정상 발화 = 과억제 없음)하나, **겨냥한 문제가 이 층에 없음.**

## 4. Decision: `reject`

- **v4.1을 nightly shedding 오탐의 fix로 채택하지 않음.** 근거: 오탐이 adaptive@1080에서 재현되지 않음(64/64 moving) → 프롬프트가 원인 층이 아님. 게이트(억제율≥60%)는 억제 대상(S0)이 0이라 적용 불가 = 전제 falsified.
- **v4.1 파일은 보존** — 버전격리(v4.0 3파일 무손상)라 회귀 기준점·미래 hardening 후보로 남김. **DEFAULT 승격 안 함**(근거 없음).
- **실피해 낮음** — 오탐은 이미 `REGISTER_SKIP_ACTIONS`로 큐 오염 차단됨. 남은 건 리포트 탈피 시그널 신뢰도(이 개체 탈피 0이라 무해).
- 누적 결론과 정합: frame-side 4레버 천장(`roi-crop-close`) + 입력이 레버 → 이번엔 그 입력마저 동일 → 비결정성이 진짜 변수.

## 5. 한계

- **단일런:** 클립당 1회 추론이라 v4.1이 **오발화 확률**을 낮추는지(반복샘플링 rate)는 측정 못 함. 두 프롬프트 단일런 모두 moving.
- **harness 버그:** Part B(v4.1 185 회귀 안전성) 미측정. 단 Part A(오탐 미재현)가 decision을 결정하므로 moot. (수정: 배치별 개별 파일 — `_build_batches.py` 반영.)
- **소표본:** Set-FP 32 · 진짜 탈피 29.

## 6. 다음 액션

1. **(별도 트랙) nightly 비결정성** — 진짜 근본원인. claude CLI temperature 제어 가능성 조사 → 불가 시 K회 majority-vote. shedding뿐 아니라 drinking↔moving 흔들림 포함. 팔로업 `nightly-classify-nondeterministic-temperature`.
2. **harness 버그 수정** — 공유 인덱스 → **배치별 개별 파일**(`_build_batches.py` 반영). 메모리 `blind-eval-workflow-per-batch-file`.
3. **v4.1 = closed** — 재개 조건: 비결정성 해결 후에도 흰모프 shedding 오발화 rate가 유의미하면 반복샘플링으로 v4.1 hardening 재검증(현재 우선순위 낮음).
