# 라벨링 관리 화면 — 큐 + 내 라벨 + owner 검수 통합

> 라벨링 웹의 "큐 1건 라벨" 외 부족했던 운영 흐름을 채운다. 큐 정정, 본인 라벨 재조회/수정,
> owner 가 다른 사람 라벨 + VLM 추론 비교/덮어쓰기, 영상 재생 불가 케이스 처리.

**상태:** 🚧 진행 중 (스펙 초안 — 사용자 검토 대기)
**작성:** 2026-05-04
**연관 SOT:** 없음 (제품 스펙은 라벨링 운영 디테일까지 안 내려감 — 이건 개발/운영 도메인)
**연관 스펙:** [`feature-r2-storage-encoding-labeling.md`](feature-r2-storage-encoding-labeling.md) §3-7 라벨링 웹

---

## 0. 발단 — 2026-05-04 prod 첫 사용 시 발견

`https://petcam-lab.vercel.app/labeling` 가동 후 사용자 (owner, `bss.rol20`) 가 큐 진입 →
다음 3가지가 막힘.

1. **큐에 idle 클립까지 노출** — 클릭한 클립 (`80a4a2a4`, 11분, `has_motion=False`,
   `r2_key=None`, file_size=264KB) 은 모션 트리거 안 된 idle 세그먼트. 영상 재생 시도 →
   r2_key 없음 → local fallback → prod 도메인에서 410 또는 cross-origin video src 실패.
2. **본인 라벨 다시 못 봄** — `/labeling/{id}` 진입 시 `getMyLabels` 로 prefill 은 동작.
   하지만 큐는 `not_.in_(labeled clip_ids)` 로 본인 라벨 클립을 빼버려서, 한 번 라벨한
   클립을 다시 찾는 진입점이 사라짐.
3. **다른 사람 라벨 / VLM 추론 결과 안 보임** — owner-override 라벨 권한은 백엔드에
   있지만 (POST `labeled_by` 필드), 프론트는 UI 가 없어서 검수 흐름 불가능.

→ 라벨링 웹의 "1인 라벨 입력" 단방향 흐름을 "다인 검수 + 자기 정정" 양방향으로 확장.

## 1. 목적

- **사용자 가치**: 라벨러가 자기 작업을 회고하고, owner 가 다른 라벨러 작업 + VLM 추론을
  같은 화면에서 비교/검수. 큐에 영상 재생 불가 클립이 섞이지 않음.
- **기술 학습**: Next.js App Router 의 동적 segment + 권한별 UI 분기, behavior_logs
  (VLM 추론) 와 behavior_labels (사람 라벨) 를 같은 클립 ID 로 join 해서 비교 표시.

## 2. 스코프

### In (이번 스펙에서 한다)

#### A. 큐 필터 정정 (버그 fix)
- `/labels/queue` 백엔드 — `has_motion=true` 필터 추가 (영상 재생 가능 보장).
- `r2_key IS NOT NULL` 도 추가 검토 — local fallback 클립이 prod 라벨링 웹에 떠도
  cross-origin 재생 불가하므로.

#### B. "내 라벨" 리스트 화면
- `/labeling/me` (라벨러 본인) — 내가 라벨한 클립을 최신순으로. 클릭하면 기존
  `/labeling/{clipId}` (이미 prefill 동작) 으로 이동 → 수정 후 저장.
- 큐 (`/labeling`) 옆에 "내 라벨" 탭/링크 추가.

#### C. 검수 화면 — owner 전용
- `/labeling/{clipId}` 페이지에 추가 섹션:
  1. **VLM 추론 결과** (behavior_logs source=vlm) — 클립의 가장 최근 추론 1건. action,
     confidence, reasoning.
  2. **다른 라벨러 라벨** (behavior_labels) — 본인 외 라벨 row 들. labeled_by (이메일
     join), action, lick_target, note, created_at.
  3. **owner 가 다른 라벨러 라벨 덮어쓰기** — 각 row 옆에 "이 라벨로 수정" 버튼 →
     prefill + `labeled_by` 명시한 POST.
- 라벨러 (비-owner) 는 위 섹션 보지 못함 (백엔드 권한 + 프론트 conditional render 둘 다).

#### D. 영상 재생 불가 케이스 명시 처리
- `/clips/{id}/file/url` 가 410 또는 r2_key 없음 응답 시 — 영상 영역에 "이 클립은 R2 에
  업로드되지 않았거나 인코딩 실패했습니다. 라벨링 불가." 안내 + 라벨 폼 disable.
- 큐 화면도 r2 없음 클립은 표시하지 않거나 (A 와 합치) "재생 불가" 배지.

### Out (이번 스펙에서 안 한다)

- **검색/날짜 필터** — A~D 끝난 후 운영 중 필요해지면 후속. 지금은 최신순 + 본인/전체
  분기만으로 운영 가능.
- **라벨 history (감사 로그)** — 같은 clip_id, labeled_by 의 row 는 1개 (UPSERT) 라
  history 가 없음. owner 가 덮어쓰면 이전 값 사라짐. 감사 필요해지면 별도 spec.
- **inline 영상 thumbnail 그리드** — 큐/내라벨 리스트는 텍스트 row 만. 썸네일 표시는
  spec §3-7 에서 이미 별도 검토 중이라 여기선 제외.
- **VLM 재추론 트리거** — 라벨링 웹에서 "재분석" 버튼 같은 것 안 만든다. 추론은 백엔드
  배치/PoC 도메인.
- **모바일 키보드 단축키** — 데스크탑/모바일 동일 UI 유지. 라벨러가 PC 에서 50건+ 처리
  하면 단축키 필요해질 수 있지만 그건 후속.

> **스코프 변경은 합의 후에만.**

## 3. 완료 조건

### A. 큐 필터 정정
- [x] 백엔드 `/labels/queue` — `has_motion=true` 필터 + `r2_key IS NOT NULL` 필터 추가
- [x] 위 변경에 대한 백엔드 테스트 추가 (`tests/test_labels_api.py`) — idle 클립과 r2 없는
  클립이 큐에서 제외되는 것 검증, 기존 테스트 (motion 클립 노출) 와 함께 통과
- [ ] 사용자 브라우저 검증 — 큐에 11분 idle 클립 노출 안 됨 (백엔드 재시작 필요)

### B. 내 라벨 리스트
- [x] 백엔드 `GET /labels/mine` — 본인 라벨한 클립을 최신 라벨 시각순으로 (라벨 + clip 메타 묶음)
- [x] 프론트 `/labeling/me` — 리스트 + 클릭 → `/labeling/{clipId}`
- [x] `/labeling` 헤더에 "큐" / "내 라벨" 탭 (Link 2개)
- [ ] 사용자 브라우저 검증 — 본인이 라벨한 클립 1건 이상 → 리스트에 표시 → 클릭 → 기존
  값 prefill → 다른 action 으로 수정 → 저장 → 리스트 갱신

### C. 검수 화면 (owner 전용)
- [x] 백엔드 `GET /clips/{id}/labels` — 권한 검사 후 owner 면 전체 라벨러, 라벨러는 본인만
  (이미 구현되어 있었음 — 코드 검토 후 변경 없음 확인)
- [x] 백엔드 `GET /clips/{id}/inference` — behavior_logs source=vlm 최신 row 1건 (없으면
  null 반환, 라벨러 호출 시 403)
- [x] 프론트 `/labeling/{clipId}` 페이지 — labels 응답에서 본인/타인 분리 → `otherLabels`
  1개+ 또는 inference 있을 때만 "검수 (owner)" 섹션 노출. labeled_by UUID 앞 8자리 표시
- [x] "이 라벨로 수정" 버튼 — confirm 모달 → `labeled_by=<원라벨러>` 명시 POST → 페이지 갱신
- [ ] 라벨러 (비-owner) 로 로그인 시 — 위 섹션 안 보임 검증 (백엔드 재시작 + 라벨러 계정으로
  진입해서 확인)

### D. 영상 재생 불가 안내
- [x] `/labeling/{clipId}` 영상 영역 — `videoUrlError` 또는 `clip.r2_key=null` 시 amber
  배지 안내 + "큐로 돌아가기" 링크 + 저장/덮어쓰기 버튼 disable
- [ ] (A 의 큐 필터로 대부분 차단되지만) 직링크 진입 시 폼 disable 확인 (수동 검증)

## 4. 체험 흐름 (CLAUDE.md 유저 시뮬레이션 룰)

### 시나리오 1 — owner 가 자기 라벨 회고

```
[화면] /labeling 큐
유저 → "내 라벨" 탭 클릭
[반응] /labeling/me 로 이동, 본인이 라벨한 클립 12건 row 표시 (최신순):
  · 2026-05-04 13:02 · 60s · 80a4a2a4 · eating_paste(dish) · "그릇 핥음"
  · 2026-05-03 18:22 · 60s · 88ec7940 · moving · -
  · ...
유저 → 첫 row 클릭
[화면] /labeling/80a4a2a4 — 영상 + 메타 + action 버튼 (eating_paste 가 emerald 활성)
       + lick_target (dish 활성) + 메모 ("그릇 핥음") + "기존 라벨 수정 중" 배지
[반응] 영상 자동 로드 완료. 폼이 기존 값으로 채워져 있음
유저 → 영상 다시 보고 → action 을 'unknown' 으로 바꿔야겠다 클릭 → "수정 + 다음" 클릭
[감정] "어 그때 잘못 봤네, 바로 고칠 수 있어서 좋다"
[반응] 200 → 다음 클립으로 (또는 큐 상위로) 이동
```

### 시나리오 2 — owner 검수, 다른 라벨러가 잘못 라벨함

```
[화면] /labeling/{clipId} (큐 진입), owner 로 로그인 상태
[반응] 영상 위쪽: 평소대로 라벨 폼
       영상 아래쪽 새 섹션 "검수 (owner)":
         · VLM 추론: drinking (conf 0.82) · "그릇 위 혀 동작"
         · 다른 라벨러:
             - labeler_alice (380d97...): eating_paste / dish / "" / 5분 전
                                                                [이 라벨로 수정]
             - labeler_bob (12abef...): drinking / dish / "" / 1시간 전
                                                                [이 라벨로 수정]
유저 (owner) → "alice 의 eating_paste 가 맞다" 판단 → "이 라벨로 수정" 클릭 (alice row)
[반응] confirm 모달: "alice 의 라벨을 'eating_paste(dish)' 로 덮어씁니다. (alice 본인 라벨로)"
유저 → 확인
[반응] POST /clips/{id}/labels with labeled_by=alice_id, action=eating_paste,
       lick_target=dish → 200 → 페이지 갱신, alice row 가 새 값으로
[감정] "검수가 한 화면에서 끝나서 좋다"
```

### 시나리오 3 — 라벨러 (비-owner) 진입

```
[화면] /labeling/{clipId} (큐 진입), labeler 로 로그인 상태
[반응] 영상 위쪽 라벨 폼만 보임. owner 검수 섹션은 보이지 않음.
       (백엔드도 다른 라벨 row 안 돌려줌)
유저 → 본인 라벨 입력 → 저장 → 다음 클립
[감정] 평소와 같음 — UI 변동 못 느낌
```

### 시나리오 4 — 큐에 r2 없는 클립 안 떠야 함

```
[화면] /labeling 큐
[반응] 12건 row, 모두 모션 + r2 업로드 완료. 11분 idle 클립은 안 보임.
유저 → 첫 클립 클릭
[화면] /labeling/{id} — 영상 정상 재생 시작
[감정] 평소대로 작업 — idle/실패 클립이 섞이지 않음
```

### 시나리오 5 — 직링크로 r2 없는 클립 진입 (예외)

```
[화면] /labeling/80a4a2a4 직링크 (URL 공유 또는 메모 클릭)
[반응] 영상 영역에 안내: "이 클립은 R2 에 업로드되지 않았거나 인코딩 실패했습니다.
       라벨링 불가." 라벨 폼 disable, "큐로 돌아가기" 링크
유저 → 큐로 돌아감
[감정] "왜 안 되는지 명확해서 답답함이 적다"
```

## 5. 설계 메모

### 5.1 큐 필터 정정 — 어디까지 막을지

**선택**: `has_motion=true` AND `r2_key IS NOT NULL` 둘 다.
- `has_motion=true`: idle 11분 클립 차단. spec §3-7 의 "라벨링 클립 = 모션 트리거 클립"
  원칙과 일치.
- `r2_key IS NOT NULL`: 백엔드 마이그레이션 전 (R2 도입 전) 클립이 라벨링 웹 prod 도메인
  에서 보이지 않게.

**대안 (안 고름)**: `r2_key IS NOT NULL` 만 — `has_motion=true` 가 사실상 동치 (현재
워크플로 상 motion 만 R2 업로드) 이지만, 데이터 정합성 깨질 때 (수동 backfill 등) 안전망
없음. 둘 다 박는 게 안전.

### 5.2 "내 라벨" 진입점 — 새 라우트 vs 큐 모드 전환

**선택**: 새 라우트 `/labeling/me` + 백엔드도 `GET /labels/mine`.
- 라우트 분리가 진입점 명확. 사용자 체험 흐름에서도 "탭" 이미지가 자연스러움.
- 백엔드 큐 API 의 `mode` 쿼리 파라미터로 합치는 안 (`?mode=mine`) 보다 코드 분기 적음.

**대안 (안 고름)**: `/labeling?tab=mine` 클라이언트 분기 — 새로고침/직링크 시 상태 보존이
URL 에 의존. 라우트 분리가 더 깔끔.

### 5.3 검수 섹션 — owner 권한 분기 위치

**선택**: 백엔드가 user 가 owner 인지 확인 후 응답 차등 (라벨러는 본인 row 만, owner 는
전체). 프론트는 응답 길이 보고 섹션 표시 여부 결정.

**대안 (안 고름)**: 프론트가 user_role 보고 다른 엔드포인트 호출 — 권한 매트릭스가 두
곳에 흩어져서 유지보수 어려움. CLAUDE.md spec §4 결정 4 ("권한 매트릭스 일원화 — 백엔드
service_role") 와 정합.

### 5.4 "이 라벨로 수정" 의 의미

owner 가 alice 의 라벨 row 를 `labeled_by=alice` 로 덮어쓴다. → alice 의 라벨이 수정됨
(alice 가 다시 봤을 때 자기 라벨이 바뀐 것을 봄).

**왜 이렇게**: 백엔드 owner-override 가 이미 `labeled_by` 명시 + UPSERT 패턴이라 자연스럽.
별도 "owner 라벨" 같은 새 row 만들면 같은 clip 에 라벨 row 가 늘어나 복잡.

**리스크**: alice 가 자기 라벨이 바뀐 걸 모를 수 있음. 후속에서 노트 자동 추가 ("owner
가 수정함 — YYYY-MM-DD") 또는 알림 이메일 검토.

### 5.5 영상 재생 불가 메시지 — 텍스트 위치

**선택**: 영상 자리에 안내 메시지 + 라벨 폼 disable. 큐 진입은 A 필터로 거의 막힘.

**대안 (안 고름)**: 영상 영역에 빈 placeholder + 라벨 폼 활성 — 영상 못 본 채 라벨 입력
하면 데이터 품질 저하. 폼 disable 이 안전.

### 5.6 백엔드 변경 최소화

- **A**: queue 쿼리 2줄 추가
- **B**: 새 엔드포인트 1개 (또는 query param 1개)
- **C**: 기존 GET /clips/{id}/labels 쿼리 분기 (owner = 전체, 라벨러 = 본인) +
  새 GET /clips/{id}/inference 1개
- **D**: 백엔드 변경 없음 (프론트만)

→ 백엔드 변경은 합쳐서 ~50 줄 + 테스트 5~8 케이스. 1일 이내.

## 6. 학습 노트

- **Next.js App Router 동적 segment 와 권한 분기**: 백엔드가 응답 차등 (owner 전체 / 라벨러
  본인) 하면 프론트는 "받은 row 수" 로 자연스럽게 분기 가능. 별도 `useUser().role` 같은
  client-side 권한 hook 안 만들어도 됨.
- **UPSERT vs INSERT**: behavior_labels 의 (clip_id, labeled_by) UNIQUE 가 owner-override
  를 자연스럽게 만들었음. row history 가 필요해지면 별도 audit 테이블이지 이 테이블에
  history 박지 말 것.
- **체험 흐름을 글로 먼저 쓰기 (CLAUDE.md 룰)**: 시나리오 1~5 을 글로 적으니 "근데 alice
  본인은 자기 라벨 바뀐 걸 어떻게 알지?" 같은 미해결 질문이 발견됨 (5.4 리스크).

## 7. 참고

- `feature-r2-storage-encoding-labeling.md` §3-6 (LabelCreate.labeled_by owner-override)
- `backend/routers/labels.py` (queue, POST/GET labels, owner-override)
- `backend/routers/clips.py` (file/url, behavior_logs 별도 라우터 없음 — 추가 필요)
- `web/src/app/labeling/[clipId]/page.tsx` (라벨 폼 + prefill 이미 구현)

## 8. 결정 (2026-05-04, 사용자 "다 알아서 해" → 안전 default)

1. **A. queue 필터**: `has_motion=true AND r2_key IS NOT NULL` 둘 다. R2 미업로드/인코딩
   실패 클립까지 차단 — 영상 재생 안 되는 클립이 큐에 떠서 라벨러 시간 낭비하는 게 더
   큰 비용.
2. **C. 다른 라벨러 표시**: UUID 앞 8자리. `auth.users` join 미도입 (서비스 키 별도 쿼리).
   라벨러 인원 적어 식별 가능. 메일 표시는 후속 (스케일 시).
3. **C. owner 덮어쓰기**: confirm 모달 박는다. "실수 클릭으로 alice 라벨 바뀜" 의 비용이
   "한 클릭 추가" 보다 큼.
4. **B. 내 라벨 리스트 정렬**: 라벨 created_at desc (방금 한 거 위). 회고 흐름 ("방금
   라벨한 거 잘못 봤네") 에 자연스럽.
