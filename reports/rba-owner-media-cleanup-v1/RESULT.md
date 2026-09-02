# RBA Owner Media Cleanup v1 — Result

완료일: 2026-08-03 KST

## 최종 결과

| 상태 | 수량 | 뜻 |
|---|---:|---|
| `media_deleted` | 46 | Owner가 이미 무효라고 확정해 R2 영상·썸네일을 물리 삭제 |
| `quarantined` | 898 | 원래 연구·라벨링 경로에서 분리해 별도 R2 quarantine 경로에 보존 |
| `source_missing` | 7 | 실행 전부터 R2 원본이 없어서 재생·판단 대상에서 제외 |

- cleanup 합계: 951
- quarantine 898개 중 canonical GT 보호: 1개
- Owner가 지금 재생하며 판단할 수 있는 영상: 897개
- `motion_clips` 삭제: 0개
- 사람 GT·사건 경계·교차검수 결과 변경: 0개

## 무결성 검증

- 검사한 R2 key: 3,896개
- 기존 원본 경로에 남은 cleanup object: 0개
- 삭제 46개의 quarantine/excluded object 잔존: 0개
- 보존 898개의 destination size/ETag 불일치: 0개
- DB 최종 상태 위반: 0개
- private manifest는 Mac mini의 사용자 전용 디렉터리에 mode 0600으로 보존하며, 이 보고서에는
  clip ID·R2 key·사용자 ID·GT 원문을 싣지 않는다.

## Owner 검수 화면

- production: `https://label.tera-ai.uk/labeling/motion/cleanup`
- 시작 진행률: 0/897
- 선택: 정상 영상으로 남기기 / 게코가 안 보임 / 게코 활동이 없음 / 판단 보류
- 선택은 append-only로 한 번만 저장하며, 삭제 후보 버튼도 즉시 R2를 삭제하지 않는다.
- 라벨러 계정은 메뉴가 보이지 않고 직접 경로 접근도 역할 홈으로 돌아간다.
- Web 검증: 109 files / 954 tests, TypeScript PASS, Vercel production build PASS.

## 다음 Gate

Owner가 897개를 끝내기 전에는 Dataset v2에 이 partition을 넣지 않는다. Dataset v2는 `keep`만
사용하며 `pending`, `uncertain`, `delete_*`, `source_missing`, `quarantined` 미결 영상은 제외한다.
