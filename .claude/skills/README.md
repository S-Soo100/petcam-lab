# `.claude/skills/`

petcam-lab에 도입된 Claude Code 스킬. 전체 큐레이션 카탈로그(도입 결정·보류 사유 포함) → [`../skills-catalog.md`](../skills-catalog.md).

## 출처

- **레포:** [affaan-m/everything-claude-code](https://github.com/affaan-m/everything-claude-code) (`main`, 2026-04-28)
- **라이선스:** MIT (재배포 + 수정 + 출처 표기 의무)
- 각 SKILL.md frontmatter에 `source:` (raw URL) + `imported_at:` (가져온 날짜) 추가됨

## 도입 스킬 (10개)

| 스킬 | 도메인 | 용도 |
|------|--------|------|
| python-patterns | 백엔드 | Python 관용구·PEP 8·타입 힌트 베스트 프랙티스 |
| python-testing | 백엔드 | pytest fixture/mock/parametrize 패턴 |
| postgres-patterns | 백엔드 | Supabase 기반 PostgreSQL 쿼리·인덱스·RLS |
| security-review | 백엔드 | 인증·시크릿·API 엔드포인트 체크리스트 |
| api-design | 백엔드 | REST API 컨벤션 (페이지네이션·에러·버전) |
| prompt-optimizer | VLM | 프롬프트 진단·개선 (advisory only) |
| regex-vs-llm-structured-text | VLM | 구조화 텍스트 파싱 결정 (regex 95% / LLM fallback) |
| cost-aware-llm-pipeline | VLM | LLM API 비용 추적·모델 라우팅·캐싱 |
| frontend-design | 프론트 | 시각 일관성 가이드 (web/ 새 화면용) |
| rules-distill | 워크플로우 | 스킬 → 룰 횡단 정리 도구 |

보류 6개 + ⚠️/❌ 등급 10개의 사유는 카탈로그 참조.

## 우선순위 룰

**스킬 가이드 < 프로젝트 룰** — 충돌 시 항상 프로젝트 룰이 우선.

| 순위 | 출처 |
|------|------|
| 1 | `CLAUDE.md` (프로젝트 페르소나·기술 스택·협업 룰) |
| 2 | `.claude/rules/donts.md` + `donts/python.md` |
| 3 | `specs/` 작업 단위 결정 |
| 4 | 스킬 (이 디렉토리) |

예: `python-patterns`가 데코레이터 적극 사용 권고하지만 우리 코드 스타일이 함수 우선이면 → 우리 스타일 우선.

## 갱신 정책

ECC 본가 업데이트와 **자동 sync 하지 않음**. 필요 시 수동 재fetch:

```bash
# 예: python-patterns 갱신
URL=$(grep ^source: .claude/skills/python-patterns/SKILL.md | cut -d' ' -f2)
curl -sf "$URL" > /tmp/skill.raw
# frontmatter source/imported_at 다시 주입 후 저장
```

리스크: 본가가 룰을 강화·완화해도 우리는 stale 상태. 6개월 단위 review 권장.
