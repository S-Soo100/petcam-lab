# EXTERNAL-TRANSFER — 외부 모델/에이전트에 전달하는 방법

> 이 portable 패키지를 다른 LLM (ChatGPT, Claude, Gemini, ...) 또는 다른 에이전트(타 레포 코딩 에이전트, codex, 외주 개발자)에게 전달하기 위한 4가지 방법.

---

## 전달 방법 비교

| 방법 | 적합 대상 | 영상 포함 | 보안 | 업데이트 |
|---|---|---|---|---|
| (A) zip + 첨부 | 한 번 리뷰 의뢰 | ✗ (별도) | 수동 관리 | one-shot |
| (B) git subtree split + push | 지속 협업 | ✗ (별도) | git access 제어 | git pull |
| (C) Claude Project / Custom GPT 업로드 | 챗봇 형태 리뷰 | ✗ | 플랫폼 정책 | 수동 재업로드 |
| (D) URL 공유 (gist/repo) | 공개 공유 | ✗ | **공개 주의** | git push |

**공통:** 영상 파일 (`{clip_id}.mp4`) 은 patient privacy 사유로 portable에 미포함. `eval/run.py` 실행에 영상 필요한 경우 본 레포 운영자가 별도 안전 채널로 전달.

---

## (A) zip + 첨부 — 가장 간단

**언제:** 1회성 prompt critique 의뢰, 모델 비교 의뢰

```bash
# 레포 루트에서
cd /Users/baek/petcam-lab
zip -r vlm-classifier-portable-$(date +%Y%m%d).zip vlm-classifier-portable/ \
  -x '*/__pycache__/*' '*/.DS_Store'
ls -lh vlm-classifier-portable-*.zip
# 약 100KB (영상 미포함)
```

전달 시 첨부 메시지:
```
v3.5 게코 행동 분류 VLM 패키지 첨부합니다.
zip 풀고 README.md 부터 읽어주세요.

요청: for-cross-review.md §1 (prompt critique) 형식으로 리뷰 부탁드립니다.

영상 데이터는 보안상 별도 전송 가능합니다 (필요 시 요청).
```

---

## (B) git subtree split + 별도 브랜치 push — 지속 협업

**언제:** 외주 개발자에게 git access 부여, 다른 레포에 sub-module 추가, 장기 협업

### 1. portable 만 담은 별도 브랜치 생성 (subtree split)

```bash
cd /Users/baek/petcam-lab

# subtree 명령으로 portable 디렉토리만 별도 브랜치로 split
git subtree split --prefix=vlm-classifier-portable -b portable/vlm-classifier-v1

# 확인 — 새 브랜치 root에 portable 컨텐츠가 바로 보임
git ls-tree portable/vlm-classifier-v1 | head
# README.md, CHALLENGE.md, HISTORY.md, data/, eval/, prompt/, ...
```

### 2. 별도 원격 레포로 push (옵션)

```bash
# 새 GitHub 레포 만들고 (e.g., teraai/vlm-classifier-portable)
git remote add portable-origin git@github.com:teraai/vlm-classifier-portable.git
git push portable-origin portable/vlm-classifier-v1:main
```

또는 **본 레포 안에 그냥 브랜치만 두고 cherry-pick 협업**:
```bash
# 외주 개발자에게 본 레포 read access + portable/* 브랜치 push 권한만 부여
git push origin portable/vlm-classifier-v1
```

### 3. 본 레포 업데이트 → 재 split

portable 디렉토리 수정 후:
```bash
# 본 레포 main에서 변경 commit
git commit -m "feat(vlm): prompt v3.6 시도"

# 재 split (새 브랜치명 또는 force)
git subtree split --prefix=vlm-classifier-portable -b portable/vlm-classifier-v2
```

---

## (C) Claude Project / Custom GPT 업로드

**언제:** 비개발자에게 챗봇 인터페이스 제공, 빠른 prompt 실험

### Claude Projects (claude.ai)
1. Project 생성 → Knowledge 섹션
2. 다음 파일 업로드 (총 ~150KB):
   - `README.md` `CHALLENGE.md` `HISTORY.md` `for-cross-review.md`
   - `prompt/system_base.md` `prompt/species/crested_gecko.md`
   - `data/classes.json` `data/README.md`
   - `data/eval-159.jsonl` `data/gt-159.jsonl` (jsonl도 file 첨부 가능)
3. Project instructions:
   ```
   당신은 v3.5 게코 행동 분류 VLM 패키지 리뷰 어시스턴트입니다.
   for-cross-review.md §1~§4 중 사용자가 지정한 형식으로 리뷰합니다.
   안티패턴 4종 (CHALLENGE.md §3) 추천 절대 금지입니다.
   ```

### Custom GPT (chat.openai.com)
- 동일하게 Knowledge 업로드. 단 파일 수 제한 확인 (현재 20개).
- jsonl이 너무 크면 `gt-159.jsonl` 만 업로드, eval은 모델이 재추론하게.

### 한계
- 영상 입력 처리 불가 (실 추론은 본 레포에서)
- 챗봇은 prompt critique / 데이터 분석 의견 제시까지만

---

## (D) Public gist / repo

**언제:** 오픈소스 release, 컨퍼런스 공유, 재현 실험 공개

### 보안 체크리스트 (공개 전 필수)
- [ ] `data/eval-159.jsonl` `data/gt-159.jsonl` 의 clip_id가 UUID 인지 (PII 없음 확인)
- [ ] `data/_export-gt.py` 의 Supabase URL/key가 환경변수 참조인지 (하드코딩 없음 확인)
- [ ] HISTORY.md / SOT 링크 중 internal repo 링크 제거 또는 placeholder 처리
- [ ] license 파일 추가 (MIT 권장, 데이터셋 별도 명시)

### Github 공개 release
```bash
# 1. subtree split (B 방법 1단계)
git subtree split --prefix=vlm-classifier-portable -b portable/release-v1.0

# 2. 새 public repo 생성
gh repo create teraai/vlm-classifier --public --description "Crested gecko behavior classification VLM (v3.5)"

# 3. push
git push https://github.com/teraai/vlm-classifier.git portable/release-v1.0:main
```

### Gist (단일 파일만)
- 어울리지 않음 (다중 파일 구조라서). zip 첨부 권장.

---

## 전달 후 외부 에이전트 응답 받기

### 결과 보고 양식 (CHALLENGE.md §7)

외부 에이전트가 시도 결과 공유 시 받아야 할 양식:

```markdown
## 시도: {짧은 이름}

### 변경
- {prompt/model/code 어디 어떻게}

### 결과 (159건 평가)
- raw: {X}/159 = {X.X}%
- feeding-merged: {X}/159 = {X.X}%
- production baseline: {X}/159 = {X.X}% (vs 85.5%, Δ = ±X.Xp)

### 5-카테고리
- held-correct: {N}
- recovered: {N}
- broken: {N}
- still-wrong-same: {N}
- still-wrong-changed: {N}

### 결론
- 채택 권장: YES/NO ({이유})
- 다음 단계: {있다면}
```

### 검증 절차

받은 결과 적용 전:
1. 새 jsonl 받기 (eval-{model}.jsonl)
2. 본 레포에서 `eval/compare.py` 로 5-카테고리 + 채택 판정 재계산 (외부 보고를 신뢰하지 않고 자체 검증)
3. 채택 권장 여부 자체 결정 (Δ > +3%p AND recovered > broken)
4. 채택 시 → `prompt/system_base.md` 또는 모델 어댑터 변경 → 본 레포 web/eval/v35/ 에 새 이름으로 라운드 시작

---

## 영상 데이터 별도 전송 (필요 시)

영상이 필요한 작업 (model comparison, residual mismatch validation):

### 안전 채널 옵션
1. **AWS S3 presigned URL** — 24시간 만료, 다운로드 1회 제한
2. **Google Drive** 공유 (조회 권한, 만료 설정)
3. **암호화 zip + 비밀번호 별도 채널** (zip은 메일, 비번은 카톡 등)

### 영상 명세
- 159 클립, 각 5~30초
- 24fps, 720p~1080p
- 총 약 ~500MB
- naming: `{clip_id}.mp4` (clip_id = data/eval-159.jsonl 와 일치)

---

## 자주 묻는 질문 (전달 받는 쪽)

### Q. 이 평가 결과 (85.5%)를 직접 재현하려면?
A. `eval/analyze.py` 만 실행하면 동일 결과 출력. 영상 불필요. README.md "1. baseline 검증" 섹션 참고.

### Q. 영상 없이 prompt critique 만 가능한가?
A. 가능. `prompt/system_base.md` + `prompt/species/crested_gecko.md` + `HISTORY.md` (왜 지금 이 형태가 됐는지) + `CHALLENGE.md` (안티패턴) 읽고 리뷰.

### Q. 새 모델 추가는?
A. `eval/run.py` 의 `ModelAdapter` ABC 상속 + `infer()` 구현. Anthropic/OpenAI는 stub 코드와 docstring 가이드 제공.

### Q. 라이센스는?
A. 본 레포 (petcam-lab) 운영자에게 문의. 데이터셋은 사용자 동의 기반이라 별도 정책.

---

## 재 split / 업데이트 워크플로

portable 디렉토리 수정 → 외부 전달 받는 사람 업데이트:

```bash
# 본 레포에서 portable/* 수정 + commit
git add vlm-classifier-portable/...
git commit -m "fix(vlm): X"

# subtree push (이미 portable repo 있으면)
git subtree push --prefix=vlm-classifier-portable portable-origin main

# 또는 새 split + force push
git subtree split --prefix=vlm-classifier-portable -b portable/vlm-classifier-v2
git push -f portable-origin portable/vlm-classifier-v2:main
```

받는 쪽:
```bash
git pull
# README.md / CHALLENGE.md / HISTORY.md 변경분 확인
```
