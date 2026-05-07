"""VLM 워커 서브패키지 — Gemini SDK 래퍼 + 폴링 워커.

`feature-vlm-worker-cloud.md` 의 코드 산출물. PoC (`web/src/app/api/inference/route.ts`)
에서 라벨링 웹이 admin 클릭으로만 돌리던 추론을, **백그라운드 워커가 모든 모션 클립**에
자동 적용하도록 production 화한 것.

서브패키지로 나눈 이유:
- `backend/vlm_worker_main.py` 가 entrypoint, 거기서 import 만.
- prompts / SDK 래퍼 / 폴링 루프가 각각 단위 테스트 가능.
- 미래에 별도 레포로 분리할 때 디렉토리 단위 그대로 옮길 수 있음.
"""
