# Gemini CLI 운영 폐기 설계

## 목적

MacBook과 Mac mini에서 Gemini CLI 실행·인증·자동 fallback 경로를 제거해. Gemini API와 과거
감사 이력은 별개이므로 유지하고, 앞으로 에이전트가 Gemini CLI를 독립 리뷰 도구로 다시
선택하거나 재설치하지 못하게 활성 운영 계약을 바꿔.

## 범위

MacBook:

- `/opt/homebrew/lib/node_modules/@google/gemini-cli` 전역 npm 패키지 제거
- `/opt/homebrew/bin/gemini` 실행 경로 제거 확인
- `~/.gemini` OAuth credential·설정 제거
- user/project `AGENTS.md`에서 Gemini CLI 허용 문구 제거, 사용·재설치 금지 명시
- ideaBank의 Gemini CLI wrapper와 자동 image fallback 제거
- active agent/rule/status 문서에서 Gemini CLI 추천 제거

Mac mini:

- P3 runtime 설치 전에 동일 inventory와 제거를 선행
- `command -v gemini`와 `~/.gemini`가 모두 없어야 runtime 설치 가능
- 제거 실패 시 P3 설치를 시작하지 않음

## 보존 경계

- Gemini API backend와 관련 credential은 이번 범위에서 유지
- Codex CLI 사용 계약은 유지
- 과거 보고서·감사·TIL의 Gemini CLI 언급은 역사 증거라 보존
- production DB/R2/media/서비스는 변경하지 않음

## 완료 조건

- MacBook에서 `command -v gemini` 실패
- MacBook에서 `~/.gemini` 없음
- active policy와 executable wrapper/fallback에서 Gemini CLI 호출 0
- ideaBank Python·JSON·bash 정적 검증 통과
- Mac mini P3 handoff에 같은 제거 게이트와 검증 명령이 기록됨
- Mac mini 실제 제거는 다음 runtime 설치 실행에서 증거와 함께 완료
