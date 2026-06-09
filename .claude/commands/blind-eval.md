# /blind-eval — Claude blind 평가 레시피

> contact sheet 를 GT 미공개 서브에이전트로 판정 → jsonl 취합 → GT 대조 분석.
> petcam-lab Claude 구독 정성 트랙(`specs/experiment-claude-subscription-rba.md`)의 표준 실행법.
> 인자 예: `/blind-eval eval-0608-claude claude_v36_blind.jsonl 6` (dir, jsonl, 에이전트 수)

## 전제
- `experiments/{dir}/sample-*/contact.jpg` 존재 (없으면 `scripts/make_*_sheets.py` 먼저 — `scripts/utils/sheets.py` 의 `make_contact_sheet*` 사용)
- `experiments/{dir}/sample-*/meta.json` 에 GT (**에이전트엔 숨김**)
- `/tmp/v{N}_prompt.txt` = `build_system_prompt(species, prompt_version='v{N}')` 출력 (예: `uv run python -c "from backend.vlm.prompts import build_system_prompt; open('/tmp/v36_prompt.txt','w').write(build_system_prompt('crested_gecko', prompt_version='v3.6'))"`)

## 1. 배치 분할 (클래스 섞이게 라운드로빈)
```bash
ls -d experiments/{dir}/sample-*/ | xargs -n1 basename | sort | \
  awk -v n=N '{b[NR%n]=b[NR%n]" "$0} END{for(i=0;i<n;i++) print "BATCH"i":"b[i]}'
```
clip_id 가 랜덤이면 정렬만으로 클래스가 섞여 blind 유지. 배치당 7~11건 권장.

## 2. 서브에이전트 N명 병렬 (general-purpose, 한 메시지에 N Task)
각 에이전트 공통 지시:
- `/tmp/v{N}_prompt.txt` Read → 분류 기준 숙지
- 담당 `{sample}/contact.jpg` 만 Read 판정 (5x6=30 / 6x6=36 프레임, 시간순 좌→우 위→아래)
- **`meta.json` 절대 Read 금지** (GT 누설 = blind 깨짐). 폴더명·파일명도 힌트 아님.
- 출력 JSON 배열만: `[{"sample":"sample-xxx","action":"<class>","confidence":0.0-1.0,"reasoning":"<영어 한 문장>"}]`
- action 은 10클래스 중 하나(eating_paste/eating_prey/drinking/defecating/shedding/basking/hiding/moving/unseen/hand_feeding). OOD 룰 먼저(사람 손/도구 보이면 hand_feeding).

## 3. 취합 → jsonl
에이전트 결과를 `experiments/{dir}/{jsonl}` 로 (sample/pred/conf 한 줄씩). ⚠️ **conf 필드 누락 주의**(포맷 표준화).

## 4. 분석
`PYTHONPATH=. uv run python scripts/analyze_{dir}_claude.py` (meta.json GT 대조: raw/feeding-merged/클래스별/OOD recall/혼동/GT 검수).

## ⚠️ 원칙 (반드시 지킬 것)
- **정성 수치 ≠ production** — Claude+contact sheet 라 Gemini 영상 정량과 직접 비교 금지. 리포트에 "정량 baseline 아님" 명기.
- **blind 불일치 = 라벨 QA 단서** — GT 오류 후보. "AI가 그랬다 → 즉시 정정" 아님. **사람이 영상 직접 확인 후** 정정 (오정정 방지).
- **미세행동 제외** — shedding/defecating/hiding/unseen 은 contact sheet 불가(2026-06-08 입증). 평가 대상에서 제외하거나 Gemini 영상 트랙으로.
- **같은 모델 자기리뷰 경계** — blind 결과를 같은 모델이 또 검증하면 편향. 휴먼 교차검증 or 다른 모델(Gemini/Codex).

---

## 🆕 frames 모드 — 개별 풀해상도 프레임 N장 (몽타주 대신)

> contact-sheet 몽타주(~72px/프레임)가 미세접촉을 뭉개 과소평가하는 걸 회피. 개별 풀해상도
> 프레임(1024px)을 따로따로 넣으면 **미세접촉 +21%p / 전체 202건 raw 79.7%** (2026-06-09, 메모리 `feedback_frames_beat_montage`).
> ⚠️ shedding(정적 허물증거)은 frames 로 **90%** 잡힘 — contact-sheet "미세행동 제외" 원칙과 다름. defecating(순간)·drinking(벽 응결수)만 여전히 바닥.

**prep**: `storage/dataset-203/analyze.py:extract_frames(src, out_dir, N)` (N=10 기본, 1024px). 오답 재측정만 N=20.
- manifest 필터 → 대상 clip → 추출 → `sample-{c8}/f_001.jpg..f_NNN.jpg` + meta.json(`{gt,src,c8}`, **GT 숨김**).
- 이미 평가한 clip 은 done set 으로 제외(재사용). **배치 8건/에이전트** 권장(contact-sheet 7~11보다 적게 — 건당 N장 Read).

**서브에이전트 (frames 모드, contact-sheet와 다른 점만)**:
- `sample-*/f_*.jpg` 를 **번호순(=시간순) 전부** Read 후 판정 (몽타주 1장 → N장).
- 결정적 순간(혀-물/먹이 접촉)이 일부 프레임에만 있을 수 있으니 빠짐없이.
- 나머지(`meta.json` 금지, OOD 먼저, JSON 배열 출력)는 contact-sheet와 동일.

**score (frames 모드)**: **jsonl read 방식 표준** (PRED 딕셔너리 하드코딩 금지 — `scripts/_score_frames_full.py` 패턴).
- 라운드별 pred 를 jsonl 로 누적 저장 → manifest GT(정정본) 대조, clip8 기준 매칭.
- 핵심 지표: raw/feeding-merged/클래스별 + **recovered**(몽타주 오답→frames 정답)/**broken** + **`→moving` 고착**(시각 한계) + **hand_feeding 이탈**(GT≠hf인데 frames=hf → GT 오류 후보).

**원칙(공통)**: 위 ⚠️ 원칙 그대로. 특히 **정지프레임 hand_feeding 후보는 사람 영상 확인 후 확정**(혀↔도구 혼동, `036a650d` 오판 실증).
