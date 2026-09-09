"""nonvlm-behavior-v0 — VLM 없이 GME 궤적 특징만으로 행동 evidence 를 뽑는 연구 스크립트 묶음.

시험지: experiments/nonvlm-behavior-v0/TEST-SHEET.md (pre-reg, 임계값 사후 변경 금지).
모듈 경계:
- run_gme_local   : gate venv 에서 production 계약 그대로 GME 실행 → 확장 artifact JSON (DB/R2 write 0)
- features        : artifact → F1~F7, F9~F11 (결정론, GT 미접근)
- head_micro      : 원본 프레임 재디코딩 → F8 (머리 끝 미세움직임)
- rules           : 특징 → 룰 v0 라벨
- scorer          : 예측 + GT + v4.0 저장 예측 → 시험지 §6 지표·§7 게이트
"""
