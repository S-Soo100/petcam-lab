# 활동필터 v0 — 사람 preflight 검수 안내 (activity-preflight-0714)

detector 판정을 **숨긴 채** 사람이 먼저 blind 로 동영상을 보고 판단한다. 그 뒤에만 detector 와 대조한다
(Claude/VLM 판정을 GT 로 쓰지 않는다 — 지시문 §314). 목적: exclude_absent / exclude_static 스위치를
카메라 A 에서 켜도 안전한지(= 활동 clip 을 잘못 제외하지 않는지) 판단.

## 검수 절차
1. 동영상 폴더 열기: `storage/activity-preflight-0714/clips/` (clip_id 파일명)
2. `review_manifest.csv` 를 order 순으로 열기 (엑셀/Numbers/텍스트 편집기)
3. 각 `<clip_id>.mp4` 를 재생하고 `human_judgment` 칸에 아래 넷 중 하나 기입:
   - **absent** — 게코가 안 보임 (프레임 내 게코 없음)
   - **static** — 게코 보이지만 활동 없음 (완전 정지, 혀·머리도 안 움직임)
   - **active** — 게코가 조금이라도 움직임 (몸 이동·머리 돌림·혀 날름 등 미세 포함)
   - **unclear** — 화질/가림으로 판단 어려움
4. 30개 다 채우면 알려줘 → `compare_preflight.py` 로 detector 와 대조해 REPORT 작성.

## 금지
- `answer_key.json` 을 미리 열지 말 것 (detector 판정 = blind 유지).
- "조금이라도 움직이면 active" — 빠르다는 이유로 미세 혀·머리 움직임을 static 으로 넘기지 말 것.

## 합격 기준 (TEST-SHEET §5)
- 사람=active 인데 detector=exclude_absent/exclude_static 인 clip 이 **1건이라도** 있으면 그 스위치는 활성화 금지.
- false exclusion 0 + precision ≥ 0.90 → 그 스위치 Phase 5 활성화 권장.
