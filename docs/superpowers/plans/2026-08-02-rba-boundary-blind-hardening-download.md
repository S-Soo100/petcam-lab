# RBA 경계 검수 블라인드 하드닝 + 공통 다운로드 구현 계획

> 실행 범위: 라벨링 웹, 경계 검수 RPC, 관련 테스트·문서·배포만 변경한다. 사람 제출·GT·R2 객체·Blind30 cohort는 변경하지 않는다.

## 사용자 체험 흐름

1. `[화면]` Owner가 마지막 이어짐 판정을 제출한다 → `[조작]` 별도 조작 없이 완료 화면을 본다 → `[반응]` 상대가 끝나기 전에는 답이나 불일치 건수 대신 “상대 검수 대기”만 보인다 → `[감정]` 상대 답을 미리 볼 수 없다는 확신을 얻는다.
2. `[화면]` 상대도 마지막 판정을 제출한다 → `[조작]` 자동 갱신 또는 “상태 새로고침”을 누른다 → `[반응]` 그때만 “경계 해결” 진입 버튼이 열린다 → `[감정]` 두 사람의 최초 답이 독립적으로 보호됐다고 느낀다.
3. `[화면]` 어느 라벨링 영상 플레이어든 하단 조작바를 본다 → `[조작]` “다운로드”를 누른다 → `[반응]` 권한이 확인된 원본 mp4 다운로드가 시작된다 → `[감정]` 영상 종류마다 다운로드 위치를 다시 찾지 않아도 된다.

## Task 1. DB를 블라인드의 최종 방어선으로 만든다

- 새 forward migration과 정적 테스트를 먼저 작성한다.
- `fn_list_rba_boundary_conflicts`는 해당 cohort·split의 모든 배정 답이 제출되기 전 `ready=false`, `items=[]`, `total=0`만 반환한다.
- `fn_resolve_rba_boundary_conflict`도 같은 완료 조건 전에는 `PT409`로 거부한다.
- 상대의 완료 개수·판정·불일치 개수는 준비 전 응답에 넣지 않는다.
- 기존 사람 제출과 배정, cohort 상태는 수정하지 않는다.

## Task 2. 완료·대기 UX를 안전하게 바꾼다

- `BoundaryConflicts` 응답에 `ready`를 추가하고 mapper/API 테스트부터 실패시킨다.
- Owner가 자기 작업을 끝낸 뒤에만 안전 상태를 조회한다.
- `ready=false`면 “내 작업 완료 · 상대 검수 대기”와 새로고침만 보이고, `ready=true`일 때만 “경계 해결” 링크가 열린다.
- 직접 `/labeling/boundary/conflicts`로 들어와도 준비 전에는 상대 답 대신 대기 화면만 보인다.
- 60초마다 상태만 자동 갱신하되, 사람 답 제출은 자동화하지 않는다.

## Task 3. 공통 영상 다운로드를 넣는다

- `ReviewVideo`에 접근 가능한 다운로드 컨트롤을 추가하는 테스트부터 작성한다.
- 일반 clip 화면은 기존 권한 확인형 `/api/clips/{id}/download/url`을 재사용한다.
- 경계 A/B 영상은 기존 assignment 권한을 재검증한 뒤 attachment signed URL을 발급하도록 경계 media API를 확장한다.
- 공통 플레이어를 쓰는 상세·Blind·튜토리얼·motion·library·불일치·router-review·quarantine·경계 화면에 clip ID 또는 다운로드 요청을 전달한다.
- 기존 영상 재생·자동재생·타임스탬프 비가림·모바일 줄바꿈은 그대로 유지한다.

## Task 4. 검증·배포·운영 확인

- 관련 Vitest와 Python migration 테스트를 실행하고 전체 Web 테스트·TypeScript·production build를 실행한다.
- 코드 리뷰 결과를 반영하고 다시 검증한다.
- migration을 production에 적용한 뒤 Vercel production을 배포한다.
- `bss.rol20@gmail.com` Chrome에서는 라벨링 웹만 확인하고 제출 버튼은 누르지 않는다. Supabase Dashboard가 필요하면 `terraaidev@gmail.com` Chrome만 사용한다.
- 배포 후 Owner 완료 화면에서 상대 답/불일치가 노출되지 않고 다운로드 버튼이 보이는지 smoke 확인한다.

## Task 5. 연구 상태를 분리 기록한다

- `specs/next-session.md`에 배포 증거와 Blind30 v2 별도 audit 결과를 기록한다.
- Blind30 v2는 이 기능과 섞지 않고 2026-08-02 07:05 KST 이후 Mac mini read-only 재검사로만 판정한다.
- 정확히 30개가 가능해질 때만 R2 30/30 이중 preflight 단계로 넘어가며, 이번 작업은 cohort/slot/GT를 만들지 않는다.
