# 놀이 상호작용 선택지 직관화 — 구현 보고서

**task_id:** interaction-choice-clarity
**작성:** 2026-07-23
**verdict:** `INTERACTION_CHOICE_CLARITY_READY_FOR_DEPLOY_REVIEW`
**branch:** `codex/interaction-help-ui` (worktree `/Users/baek/petcam-lab/.worktrees/interaction-help-ui`)

---

## 0. 시작 계약 (HANDOFF_OK)

validator 전문 (그대로):

```text
HANDOFF_OK task=interaction-choice-clarity repo=interaction-help-ui commit=da031ca2 runtime=none
```

- `cd /Users/baek/petcam-lab/.worktrees/interaction-help-ui && uv run python scripts/verify_agent_handoff.py --manifest …/2026-07-23-interaction-choice-clarity.md` → `HANDOFF_OK` 통과.
- 착수 시 branch `codex/interaction-help-ui`, HEAD `da031ca20de6611be214397d883fac256424a7df`.
- 착수 시 `git status --short` = handoff manifest 하나만 untracked (다른 세션 소유 변경 없음).
- design·plan front matter를 처음부터 끝까지 읽고 착수.

---

## 1. 원인과 화면 전/후

### 원인
공용 `GroundTruthForm`의 놀이 상호작용 방법 선택이 `올라타기 / 밀기 / 회전시키기 / 쫓기 / 반복해서 돌아오기 / 기타`라는 **설명 없는 작은 칩**으로만 나열됐다. 라벨러는 (a) 항목이 서로 배타적인지, (b) 쳇바퀴에서 무엇을 우선 골라야 하는지, (c) `밀기`와 `회전시키기`를 동시에 골라도 되는지를 알 수 없어 관찰 기준이 사라졌다. 안내문에 같은 단어를 반복해도 판단 기준은 생기지 않았다.

### 화면 전
```text
2. 사용한 방법 선택 · 하나 이상 필수
(쳇바퀴 선택 시) 쳇바퀴를 선택했다면 올라타기·밀기·회전시키기 중 실제로 확인한 방법을 하나 이상 골라줘.
[올라타기] [밀기] [회전시키기] [쫓기] [반복해서 돌아오기] [기타]   ← 설명 없는 flex-wrap 칩
```

### 화면 후 (wheel 선택 시)
```text
2. 사용한 방법 선택 · 하나 이상 필수
쳇바퀴에서 실제로 본 행동은?
여러 개 선택할 수 있어. 실제로 확인한 행동을 모두 골라줘.

자주 확인하는 행동
[✓ 위·안에 올라감]            [○ 밖에서 밀거나 건드림]
   몸이나 발을 쳇바퀴 위 또는      올라타지 않고 발·머리·몸으로
   안에 올렸어요.                쳇바퀴를 밀었어요.
[✓ 쳇바퀴를 실제로 돌림]
   게코의 움직임 때문에 쳇바퀴가 회전했어요.

그 밖에 함께 본 행동
[○ 움직이는 물체를 따라감]      [○ 떠났다가 다시 찾아옴]
[○ 다른 방식으로 상호작용함]

선택한 내용: 쳇바퀴 위·안에 올라감 · 쳇바퀴를 실제로 돌림
```
- 모바일(<`sm`)은 1열, `sm` 이상은 2열 그리드.
- 각 카드는 전체가 `<button type="button">`이며 `aria-pressed`로 선택 상태를 노출하고, 제목·설명·텍스트 체크(`✓`/`○`)로 아이콘 없이도 의미가 전달된다.
- 비-wheel 사물(`toy`/`other`/`uncertain`)은 제목이 `이 물체를 어떻게 사용했나?`이고 여섯 항목을 그룹 구분 없이 한 목록으로 보여준다. 문구의 명사는 `물체`로 유지된다.

---

## 2. 변경 파일과 task별 commit SHA

| Task | commit | 파일 |
|---|---|---|
| Task 1 (표시 계약) | `cc614dc` | `web/src/lib/labelingDisplay.ts`, `web/src/lib/labelingDisplay.test.ts` |
| Task 2 (설명 카드 UI) | `94d070d` | `web/src/app/labeling/_labeling-forms.tsx` |
| Task 3 (문서·보고서) | HEAD (docs·보고서 커밋) | `docs/FEATURES.md`, `specs/next-session.md`, `.claude/donts-audit.md`, 본 보고서 |

**추가된 표시 계약 (입력 화면 전용, 저장 계층과 분리):**
- `interactionChoiceCopy(type, enrichmentObject)` — 카드 제목·설명. `wheel`이면 `물체`→`쳇바퀴` 치환한 **새 객체** 반환(원본 map mutate 없음).
- `interactionChoiceGroups(enrichmentObject)` — `wheel`은 `{primary:[ride,push,rotate], secondary:[chase,repeated_return,other]}`, 비-wheel은 `{primary:[6개], secondary:[]}`. 매 호출 새 배열.
- `interactionSelectionSummary(enrichmentObject, selected)` — 전달 순서 보존 자연어 요약, 빈 선택은 `null`.
- `InteractionChoiceCard` — `_labeling-forms.tsx` 내부 presentational helper.

---

## 3. RED→GREEN 증거와 전체 검증 수치

### TDD RED→GREEN (Task 1)
- **RED:** 신규 export 없음 상태로 `npx vitest run src/lib/labelingDisplay.test.ts` → `8 failed | 45 passed` (`interactionChoiceCopy is not a function` 등).
- **GREEN:** 최소 구현 후 재실행 → `53 passed`.
- 신규 테스트 8개: wheel 제목·설명 치환(3 enum 정확 일치) / 비-wheel 기본 문구 유지 / wheel primary·secondary 순서 / 비-wheel 단일 그룹 / groups 새 배열 반환 / 요약 wheel 문맥·순서 보존 / 요약 순서 비정렬 / 빈 선택 null / `INTERACTION_LABELS`·`formatDimensionValue` 불변.

### 전체 자동 검증 (Task 3)
| 항목 | 결과 |
|---|---|
| web 전체 테스트 (`npm test -- --run`) | **536 passed** (51 files) |
| TypeScript (`npx tsc --noEmit`) | exit 0 (clean) |
| Python 회귀 (`uv run pytest -q`) | **694 passed** |
| `git diff --check` | clean (whitespace 오류 0) |
| Next build (`npm run build`) | **미실행 — 레포 안전 훅(donts#9)이 차단.** §6 참조 |

---

## 4. enum / API / DB / payload 불변 증거

`git diff 7da1510a…HEAD -- web/src/lib/labelingV2.ts web/src/app/api migrations` → **출력 0 (빈 diff)**.

`git diff --name-only 7da1510a…HEAD` = 변경 파일 전부:
```text
docs/superpowers/plans/2026-07-23-interaction-choice-clarity.md   (기존 plan, base 이후 없음 — 실제 소스 변경 아님)
web/src/app/labeling/_labeling-forms.tsx
web/src/lib/labelingDisplay.test.ts
web/src/lib/labelingDisplay.ts
```
- `InteractionType` enum / `INTERACTION_TYPES` 배열 / API route / RPC / migration 파일 **변경 0**.
- `interaction_types` 배열 toggle은 byte-equivalent 유지 — 콜백 파라미터 이름만 `x`→`value`로 바꿨고 로직(`includes ? filter : […, type]`)과 순서는 동일. 저장 payload 동일.
- 기존 피드백 출력 불변: `INTERACTION_LABELS.ride === '올라타기'`, `formatDimensionValue('interaction_types', ['ride','rotate']) === '올라타기, 회전시키기'` 회귀 테스트로 고정. `INTERACTION_LABELS`는 `formatDimensionValue`에서 계속 사용.
- 이미 저장된 GT 변환·마이그레이션 없음.

---

## 5. 공유 화면 영향 범위 (legacy v2 · motion v3 · 튜토리얼 · 보정)

변경은 전부 공용 `GroundTruthForm`(`_labeling-forms.tsx`) 내부의 interaction section 한 곳이다. `<GroundTruthForm>`을 렌더하는 화면 4곳이 같은 카드 UX를 공유함을 확인:

| 화면 | 파일 |
|---|---|
| legacy v2 production 상세 | `src/app/labeling/[clipId]/page.tsx` |
| motion v3 상세 | `src/app/labeling/motion/[clipId]/page.tsx` |
| 튜토리얼 lesson | `src/app/labeling/tutorial/[position]/page.tsx` |
| owner 현재 GT 보정 | `src/app/labeling/_correction-panel.tsx` |

네 화면 모두 별도 조건 분기 없이 새 카드·그룹·요약을 그대로 상속한다. enrichment 사물 선택(1단계)·`FieldError`·저장 흐름은 손대지 않았다.

---

## 6. build 및 preview 검증 여부

- **Next build: 미검증.** 세션 안전 훅 `~/.claude/hooks/dangerous-guard.sh`가 Claude Code 내부 `npm run build`를 donts#9로 차단한다. handoff §4.8·plan Step 1에 따라 `tsc`를 build 성공으로 대체 주장하지 않는다. tsc `--noEmit`은 통과했다.
  - **owner 실행 명령:**
    ```bash
    cd /Users/baek/petcam-lab/.worktrees/interaction-help-ui/web && npm run build
    ```
- **브라우저 preview: 미검증.** Chrome 확장 미연결·Deployment Protection 대상. 아래 owner 확인 절차(§8) 대기.

---

## 7. 최종 branch · HEAD · origin 동기화 · working tree

- branch: `codex/interaction-help-ui`
- HEAD: docs·보고서 커밋(이 보고서를 포함하는 커밋 = 브랜치 HEAD). 자기 커밋은 자기 해시를 담을 수 없어 값 하드코딩 대신 `git rev-parse HEAD`로 확인 — 실제 값은 전달 메시지에 기재.
- 커밋 순서: `da031ca2`(plan, handoff base) → `cc614dc`(Task1) → `94d070d`(Task2) → docs·보고서 커밋(HEAD).
- origin 동기화: `git push origin codex/interaction-help-ui` 완료, local == `origin/codex/interaction-help-ui`.
- working tree: handoff manifest(`2026-07-23-interaction-choice-clarity.md`)만 untracked로 잔류(전달용, 구현 커밋에 미포함). 그 외 clean.

---

## 8. 하지 않은 작업과 남은 owner 검수

### 이번 구현에서 하지 않은 것 (Stop Point)
- main FF/merge, Vercel production 배포, production DB write — **안 함**.
- 저장 enum·API·migration·RPC·DB·기존 GT 변환 — 없음.
- 새 npm 의존성·영상 예시·썸네일·애니메이션·자동 판정(`playing`)·selector/VLM/Python Evidence 변경 — 없음.
- 다른 worktree·다른 세션 파일 수정 — 없음.

### 남은 owner / Codex 검수
1. `npm run build`를 owner 터미널에서 실행해 프로덕션 빌드 성공 확인(§6 명령).
2. preview에서 다음을 육안 확인:
   ```text
   wheel 선택 → 질문·복수 안내
   ride만 선택 → 위·안에 올라감 요약
   push+rotate 선택 → 두 카드와 두 요약 모두 유지
   secondary 선택 → 드문 행동 그룹에서 정상 토글
   모바일 폭 → 1열, sm 이상 → 2열
   저장 payload → 기존 enum 배열과 동일
   ```
3. owner/Codex가 diff·preview 확인 후 별도 승인해야 배포로 넘어간다. 코드 완료만으로 배포하지 않는다.

**최종 판정:** 모든 자동 검증(web 536·tsc·pytest 694·diff·불변 감사) 충족, Next build·preview는 owner 실행 대기 → `INTERACTION_CHOICE_CLARITY_READY_FOR_DEPLOY_REVIEW`.
