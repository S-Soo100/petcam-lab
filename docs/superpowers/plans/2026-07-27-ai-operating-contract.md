# AI Research Operating Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ChatGPT 연구 작업의 P0~P4 권한, 모델 선택, 장기 실행, provenance를 안정 문서와 기계 검증 가능한 run manifest로 고정한다.

**Architecture:** 사람이 읽는 `AI-OPERATING-CONTRACT.md`와 실행별 JSON manifest를 분리한다. 새 stdlib validator가 JSON 구조, permission/action 조합, 모델 provenance, Git HEAD·branch·clean 상태, design/plan 추적 여부를 fail-closed로 검사한다. 기존 `verify_agent_handoff.py`는 변경하지 않고 AGENTS/CLAUDE에는 짧은 링크만 추가한다.

**Tech Stack:** Python 3.12 stdlib (`json`, `dataclasses`, `pathlib`, `subprocess`, `argparse`), JSON Schema Draft 2020-12, pytest, Markdown.

## Global Constraints

- 승인된 작업 패키지의 P0~P2는 중간 승인 없이 완료한다.
- P3는 manifest의 exact target·rollback·canary와 Owner 작업 패키지 승인이 필요하다.
- P4는 실행 직전 별도 Owner 승인이 필요하다.
- 비밀번호, API key, webhook, cookie, signed URL, 실제 secret 값은 문서·manifest·로그에 저장하지 않는다.
- 모델을 대체할 때 `requested_*`, `actual_*`, fallback 이유를 기록한다. 확인할 수 없으면 `unverified`로 쓴다.
- 기존 `scripts/verify_agent_handoff.py`와 `docs/agent-execution-contract.md`의 안전 경계를 약화하지 않는다.
- Mac mini 이전, dataset inventory, model benchmark, production 배포는 이 계획의 범위가 아니다.
- 모든 코드 변경은 TDD RED→GREEN으로 수행하고 task별 커밋을 만든다.

---

### Task 1: 안정 운영 계약 문서

**Files:**
- Create: `docs/research/AI-OPERATING-CONTRACT.md`
- Create: `tests/test_ai_operating_contract.py`

**Interfaces:**
- Consumes: `docs/superpowers/specs/2026-07-27-ai-operating-contract-design.md`
- Produces: 사람이 읽는 P0~P4·model profile·long-running·reporting 정본.

- [ ] **Step 1: 문서 계약의 RED 테스트 작성**

```python
from pathlib import Path


CONTRACT = Path("docs/research/AI-OPERATING-CONTRACT.md")


def test_ai_operating_contract_contains_permission_and_model_contracts() -> None:
    text = CONTRACT.read_text(encoding="utf-8")
    for required in (
        "P0",
        "P1",
        "P2",
        "P3",
        "P4",
        "P0~P2",
        "frontier_planning",
        "critical_engineering",
        "standard_execution",
        "independent_review",
        "requested_model",
        "actual_model",
        "RUN-MANIFEST",
    ):
        assert required in text


def test_ai_operating_contract_keeps_destructive_actions_owner_gated() -> None:
    text = CONTRACT.read_text(encoding="utf-8")
    assert "P4는 항상 별도 Owner 승인" in text
    assert "비밀번호·API key·webhook·cookie·signed URL을 기록하지 않는다" in text
```

- [ ] **Step 2: RED 확인**

Run: `uv run pytest -q tests/test_ai_operating_contract.py`

Expected: `FileNotFoundError` because `AI-OPERATING-CONTRACT.md` does not exist.

- [ ] **Step 3: 운영 계약 작성**

문서는 다음 순서와 exact 표를 사용한다.

```markdown
# AI 연구 운영 계약

## 권한 등급

| 등급 | 자동 실행 범위 |
|---|---|
| P0 | read-only 코드·문서·로그·DB SELECT |
| P1 | 격리 worktree 구현·테스트·문서·feature commit/push |
| P2 | Preview·disposable DB·rollback probe·non-production canary |
| P3 | exact target·rollback·canary가 승인된 production 변경 |
| P4 | 삭제·destructive git·credential 변경·비용 확대 |

승인된 작업 패키지에서 P0~P2는 중간 승인 없이 완료한다.
P4는 항상 별도 Owner 승인이다.

## Model profile

| profile | 현재 mapping | 역할 |
|---|---|---|
| frontier_planning | gpt-5.6-sol / ultra | 연구 설계·최종 판정 |
| critical_engineering | gpt-5.6-sol / high~xhigh | DB·보안·동시성·배포 검수 |
| standard_execution | gpt-5.6-terra / medium~high | 구현·테스트·문서 |
| independent_review | 작성자와 다른 model family 또는 독립 세션 | 교차검수 |

모델 provenance는 requested_model, actual_model, requested_reasoning,
actual_reasoning, fallback_reason으로 기록한다.

## 비밀값

비밀번호·API key·webhook·cookie·signed URL을 기록하지 않는다.
capability_available과 credential_source_name만 기록한다.
```

설계 §3~§9의 승인 범위, P3 조건, 하위 agent 권한 상속, Desktop≠daemon, heartbeat 변화 알림,
resume, 보고 필드를 문서에 그대로 포함한다.

- [ ] **Step 4: GREEN 확인**

Run: `uv run pytest -q tests/test_ai_operating_contract.py`

Expected: `2 passed`.

- [ ] **Step 5: Task 1 커밋**

```bash
git add docs/research/AI-OPERATING-CONTRACT.md tests/test_ai_operating_contract.py
git commit -m "docs: AI 연구 운영 계약 추가"
```

---

### Task 2: JSON Schema와 안전한 example

**Files:**
- Create: `docs/research/RUN-MANIFEST.schema.json`
- Create: `docs/research/RUN-MANIFEST.example.json`
- Modify: `tests/test_ai_operating_contract.py`

**Interfaces:**
- Consumes: Task 1의 P0~P4·model profile 계약.
- Produces: `schema_version=1`인 JSON object와 기계 검증용 field allowlist.

- [ ] **Step 1: schema RED 테스트 추가**

```python
import json


SCHEMA = Path("docs/research/RUN-MANIFEST.schema.json")
EXAMPLE = Path("docs/research/RUN-MANIFEST.example.json")


def test_run_manifest_schema_is_closed_and_has_required_sections() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["additionalProperties"] is False
    assert schema["required"] == [
        "schema_version",
        "task_id",
        "objective",
        "source",
        "runtime",
        "model",
        "authorization",
        "data",
        "budget",
        "safety",
        "stop_conditions",
        "deliverables",
    ]


def test_run_manifest_example_contains_no_secret_fields() -> None:
    example = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    forbidden = {"password", "api_key", "webhook", "cookie", "signed_url", "secret"}

    def keys(value: object) -> set[str]:
        if isinstance(value, dict):
            return set(value) | set().union(*(keys(v) for v in value.values()))
        if isinstance(value, list):
            return set().union(*(keys(v) for v in value), set())
        return set()

    assert not (keys(example) & forbidden)
    assert example["authorization"]["max_permission"] == "P2"
```

- [ ] **Step 2: RED 확인**

Run: `uv run pytest -q tests/test_ai_operating_contract.py`

Expected: two failures because schema and example files are missing.

- [ ] **Step 3: Draft 2020-12 schema 작성**

Top-level schema는 아래 required와 `additionalProperties: false`를 사용한다.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://tera-ai.uk/schemas/research-run-manifest-v1.json",
  "title": "RBA Research Run Manifest v1",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "schema_version", "task_id", "objective", "source", "runtime", "model",
    "authorization", "data", "budget", "safety", "stop_conditions", "deliverables"
  ]
}
```

각 nested object도 `additionalProperties: false`로 닫고 다음 property를 정의한다.

```text
source: execution_repo, branch, commit_sha, design_path, plan_path, require_clean
runtime: implementation_host, runtime_kind, runtime_host, runtime_label
model: profile, surface, requested_model, requested_reasoning, actual_model,
       actual_reasoning, fallback_reason
authorization: approved_by, approved_at, max_permission, allowed_actions,
               p3_targets, p4_actions
data: dataset_version, splits, privacy_class, media_contract
budget: max_provider_calls, max_cost_krw, max_wall_minutes, deadline
safety: requires_host_guard, requires_lock, requires_rollback,
        requires_residue_zero, temp_media_must_be_zero
stop_conditions: non-empty string array
deliverables: non-empty string array
```

Enums:

```text
profile = frontier_planning | critical_engineering | standard_execution |
          independent_review | local_assistant
surface = desktop | cli | api | local
reasoning = low | medium | high | xhigh | ultra | unverified | null
permission = P0 | P1 | P2 | P3 | P4
runtime_kind = none | oneshot | launchagent | server | scheduled-job | mobile-build
privacy_class = public | internal | sensitive
```

- [ ] **Step 4: P2 example 작성**

Example은 `/Users/example/petcam-lab`, 40자리 zero SHA, `max_permission=P2`,
`allowed_actions=["docs_write", "feature_branch_commit", "feature_branch_push", "preview_deploy", "disposable_db"]`,
`p3_targets=[]`, `p4_actions=[]`, `actual_model=null`, `actual_reasoning=null`을 사용한다. 실제 credential,
email, hostname, project id를 넣지 않는다.

- [ ] **Step 5: GREEN 확인**

Run: `uv run pytest -q tests/test_ai_operating_contract.py`

Expected: `4 passed`.

- [ ] **Step 6: JSON 문법 검증**

Run:

```bash
python3 -m json.tool docs/research/RUN-MANIFEST.schema.json >/dev/null
python3 -m json.tool docs/research/RUN-MANIFEST.example.json >/dev/null
```

Expected: exit 0 for both files.

- [ ] **Step 7: Task 2 커밋**

```bash
git add docs/research/RUN-MANIFEST.schema.json docs/research/RUN-MANIFEST.example.json tests/test_ai_operating_contract.py
git commit -m "docs: 연구 run manifest schema 추가"
```

---

### Task 3: 순수 parser와 permission fail-closed 검증

**Files:**
- Create: `scripts/verify_research_run_manifest.py`
- Create: `tests/test_verify_research_run_manifest.py`

**Interfaces:**
- Consumes: Task 2의 manifest v1 field names와 enums.
- Produces: `parse_run_manifest(path: Path) -> ResearchRunManifest`, `ManifestError(code: str)`.

- [ ] **Step 1: parser·permission RED 테스트 작성**

```python
import json
from pathlib import Path

import pytest

from scripts.verify_research_run_manifest import ManifestError, parse_run_manifest


def write_json(path: Path, value: dict[str, object]) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def base_manifest() -> dict[str, object]:
    return {
        "schema_version": 1,
        "task_id": "research-contract-test",
        "objective": "validate manifest",
        "source": {
            "execution_repo": "/tmp/repo",
            "branch": "codex/test",
            "commit_sha": "0" * 40,
            "design_path": "/tmp/repo/design.md",
            "plan_path": "/tmp/repo/plan.md",
            "require_clean": True,
        },
        "runtime": {
            "implementation_host": "dev-mac.local",
            "runtime_kind": "none",
            "runtime_host": None,
            "runtime_label": None,
        },
        "model": {
            "profile": "standard_execution",
            "surface": "desktop",
            "requested_model": "gpt-5.6-terra",
            "requested_reasoning": "high",
            "actual_model": None,
            "actual_reasoning": None,
            "fallback_reason": None,
        },
        "authorization": {
            "approved_by": "owner",
            "approved_at": "2026-07-27T00:00:00+09:00",
            "max_permission": "P2",
            "allowed_actions": ["docs_write", "preview_deploy"],
            "p3_targets": [],
            "p4_actions": [],
        },
        "data": {
            "dataset_version": "none",
            "splits": [],
            "privacy_class": "internal",
            "media_contract": "none",
        },
        "budget": {
            "max_provider_calls": 0,
            "max_cost_krw": 0,
            "max_wall_minutes": 60,
            "deadline": None,
        },
        "safety": {
            "requires_host_guard": False,
            "requires_lock": False,
            "requires_rollback": False,
            "requires_residue_zero": False,
            "temp_media_must_be_zero": True,
        },
        "stop_conditions": ["head_mismatch", "secret_exposure"],
        "deliverables": ["REPORT.md"],
    }


def test_parse_accepts_p2_start_manifest(tmp_path: Path) -> None:
    parsed = parse_run_manifest(write_json(tmp_path / "run.json", base_manifest()))
    assert parsed.max_permission == "P2"
    assert parsed.requested_model == "gpt-5.6-terra"


@pytest.mark.parametrize("secret_key", ["password", "api_key", "webhook", "cookie", "signed_url", "secret"])
def test_parse_rejects_secret_fields(tmp_path: Path, secret_key: str) -> None:
    value = base_manifest()
    value[secret_key] = "redacted"
    with pytest.raises(ManifestError, match="secret_field_forbidden"):
        parse_run_manifest(write_json(tmp_path / "run.json", value))
```

Permission tests must also cover:

```python
def test_p2_rejects_production_action(tmp_path: Path) -> None:
    value = base_manifest()
    value["authorization"]["allowed_actions"] = ["production_deploy"]
    with pytest.raises(ManifestError, match="permission_scope_mismatch"):
        parse_run_manifest(write_json(tmp_path / "run.json", value))


def test_p3_requires_exact_target_rollback_and_canary(tmp_path: Path) -> None:
    value = base_manifest()
    value["authorization"].update({
        "max_permission": "P3",
        "allowed_actions": ["production_deploy"],
        "p3_targets": [],
    })
    with pytest.raises(ManifestError, match="p3_authorization_missing"):
        parse_run_manifest(write_json(tmp_path / "run.json", value))


def test_p4_requires_separate_approval_reference(tmp_path: Path) -> None:
    value = base_manifest()
    value["authorization"].update({
        "max_permission": "P4",
        "allowed_actions": ["r2_delete"],
        "p4_actions": [{"action": "r2_delete", "target": "bounded-canary", "approval_ref": ""}],
    })
    with pytest.raises(ManifestError, match="p4_authorization_missing"):
        parse_run_manifest(write_json(tmp_path / "run.json", value))
```

- [ ] **Step 2: RED 확인**

Run: `uv run pytest -q tests/test_verify_research_run_manifest.py`

Expected: collection error because module is missing.

- [ ] **Step 3: 최소 parser 구현**

```python
PERMISSION_ACTIONS = {
    "P0": frozenset(),
    "P1": frozenset({"docs_write", "local_code_write", "feature_branch_commit", "feature_branch_push"}),
    "P2": frozenset({"preview_deploy", "disposable_db", "rollback_probe", "nonproduction_canary"}),
    "P3": frozenset({"production_migration", "production_deploy", "runtime_service_write"}),
    "P4": frozenset({"database_delete", "r2_delete", "destructive_git", "credential_change", "cost_limit_increase"}),
}
FORBIDDEN_SECRET_KEYS = frozenset({"password", "api_key", "webhook", "cookie", "signed_url", "secret"})


class ManifestError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def allowed_actions(level: str) -> frozenset[str]:
    order = ("P0", "P1", "P2", "P3", "P4")
    if level not in order:
        raise ManifestError("invalid_permission_level")
    result: set[str] = set()
    for current in order[: order.index(level) + 1]:
        result.update(PERMISSION_ACTIONS[current])
    return frozenset(result)
```

`parse_run_manifest`는 recursive key 검사, top-level/nested exact allowlist, scalar type, enum,
SHA40, 절대경로, nonnegative budget, non-empty stop/deliverables를 검증한다. P3 target object는
`kind`, `target`, `rollback`, `canary`가 모두 non-empty여야 하고 P4 action은 `action`, `target`,
`approval_ref`가 모두 non-empty여야 한다.

- [ ] **Step 4: GREEN 확인**

Run: `uv run pytest -q tests/test_verify_research_run_manifest.py`

Expected: all parser and permission tests pass.

- [ ] **Step 5: Task 3 커밋**

```bash
git add scripts/verify_research_run_manifest.py tests/test_verify_research_run_manifest.py
git commit -m "feat: 연구 run manifest 권한 검증기 추가"
```

---

### Task 4: Git·artifact·runtime·final provenance 검증

**Files:**
- Modify: `scripts/verify_research_run_manifest.py`
- Modify: `tests/test_verify_research_run_manifest.py`

**Interfaces:**
- Consumes: Task 3 `ResearchRunManifest`, `ManifestError`.
- Produces: `validate_run_manifest(path: Path, phase: str, runner=subprocess.run) -> RunSummary` and CLI markers `RUN_MANIFEST_OK` / `RUN_MANIFEST_FAIL`.

- [ ] **Step 1: Git·phase RED 테스트 작성**

Temporary repo fixture를 만들고 아래를 검증한다.

```python
def test_validate_start_requires_exact_head_branch_clean_and_tracked_artifacts(tmp_path: Path) -> None:
    repo, design, plan, sha = committed_repo(tmp_path)
    value = base_manifest()
    value["source"].update({
        "execution_repo": str(repo),
        "branch": "codex/test",
        "commit_sha": sha,
        "design_path": str(design),
        "plan_path": str(plan),
    })
    git(repo, "branch", "-m", "codex/test")
    summary = validate_run_manifest(write_json(tmp_path / "run.json", value), phase="start")
    assert summary.commit_short == sha[:8]


def test_validate_rejects_dirty_tree(tmp_path: Path) -> None:
    repo, design, plan, sha = committed_repo(tmp_path)
    value = manifest_for_repo(repo, design, plan, sha)
    (repo / "dirty.txt").write_text("dirty", encoding="utf-8")
    with pytest.raises(ManifestError, match="dirty_tree"):
        validate_run_manifest(write_json(tmp_path / "run.json", value), phase="start")


def test_final_phase_requires_actual_model_and_reasoning(tmp_path: Path) -> None:
    repo, design, plan, sha = committed_repo(tmp_path)
    value = manifest_for_repo(repo, design, plan, sha)
    with pytest.raises(ManifestError, match="actual_model_missing"):
        validate_run_manifest(write_json(tmp_path / "run.json", value), phase="final")
```

추가 cases: `repo_missing`, `repo_not_git_root`, `head_mismatch`, `branch_mismatch`,
`artifact_missing`, `artifact_outside_repo`, `artifact_untracked`, runtime kind `none`의 host/label 금지,
non-none runtime의 host/label 필수, final에서 `actual_model="unverified"`와
`actual_reasoning="unverified"` 허용.

- [ ] **Step 2: RED 확인**

Run: `uv run pytest -q tests/test_verify_research_run_manifest.py`

Expected: failures because `validate_run_manifest` and Git/runtime checks are missing.

- [ ] **Step 3: Git·runtime validator 구현**

```python
@dataclass(frozen=True, slots=True)
class RunSummary:
    task_id: str
    repo_name: str
    commit_short: str
    permission: str
    model: str
    runtime: str


def validate_run_manifest(
    path: Path,
    *,
    phase: str,
    runner: Runner = subprocess.run,
) -> RunSummary:
    if phase not in {"start", "final"}:
        raise ManifestError("invalid_phase")
    manifest = parse_run_manifest(path)
    repo = validate_repo_and_git_state(manifest, runner)
    validate_artifact(repo, manifest.design_path, manifest.commit_sha, runner)
    validate_artifact(repo, manifest.plan_path, manifest.commit_sha, runner)
    if phase == "final":
        if manifest.actual_model is None:
            raise ManifestError("actual_model_missing")
        if manifest.actual_reasoning is None:
            raise ManifestError("actual_reasoning_missing")
    return RunSummary(
        task_id=manifest.task_id,
        repo_name=repo.name,
        commit_short=manifest.commit_sha[:8],
        permission=manifest.max_permission,
        model=manifest.actual_model or manifest.requested_model,
        runtime=format_runtime(manifest),
    )
```

CLI 성공 전문:

```text
RUN_MANIFEST_OK task=<task_id> repo=<repo> commit=<8sha> permission=<P> model=<model> runtime=<runtime>
```

실패 전문은 민감값 없이 `RUN_MANIFEST_FAIL code=<stable_code>`와 exit 2만 출력한다.

- [ ] **Step 4: GREEN 확인**

Run: `uv run pytest -q tests/test_verify_research_run_manifest.py`

Expected: all tests pass.

- [ ] **Step 5: CLI smoke**

Run:

```bash
uv run python scripts/verify_research_run_manifest.py \
  --manifest docs/research/RUN-MANIFEST.example.json \
  --phase start \
  --schema-only
```

Expected:

```text
RUN_MANIFEST_SCHEMA_OK task=research-run-example permission=P2
```

- [ ] **Step 6: Task 4 커밋**

```bash
git add scripts/verify_research_run_manifest.py tests/test_verify_research_run_manifest.py
git commit -m "feat: 연구 run manifest Git·runtime 검증 추가"
```

---

### Task 5: 짧은 진입 링크·중앙 카탈로그·실행 예제 연결

**Files:**
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`
- Modify: `docs/research/README.md`
- Modify: `docs/research/catalog.json`
- Modify: `docs/superpowers/specs/2026-07-27-rba-research-system-v1-design.md`
- Modify: `specs/next-session.md`
- Modify: `tests/test_ai_operating_contract.py`

**Interfaces:**
- Consumes: Tasks 1~4의 contract, schema, validator CLI.
- Produces: 모든 agent의 짧은 진입점과 중앙 추적 항목.

- [ ] **Step 1: 링크 길이·발견성 RED 테스트 추가**

```python
def test_agent_entrypoints_link_contract_without_copying_it() -> None:
    for path in (Path("AGENTS.md"), Path("CLAUDE.md")):
        text = path.read_text(encoding="utf-8")
        assert "docs/research/AI-OPERATING-CONTRACT.md" in text
        assert "verify_research_run_manifest.py" in text


def test_catalog_registers_ai_operating_contract() -> None:
    catalog = json.loads(Path("docs/research/catalog.json").read_text(encoding="utf-8"))
    item = next(row for row in catalog["research"] if row["id"] == "ai-operating-contract-v1")
    assert item["status"] == "operational"
    assert "docs/research/AI-OPERATING-CONTRACT.md" in item["canonical"]["documents"]
```

- [ ] **Step 2: RED 확인**

Run: `uv run pytest -q tests/test_ai_operating_contract.py`

Expected: failures because entry links and catalog item are absent.

- [ ] **Step 3: AGENTS·CLAUDE에 짧은 링크 추가**

각 파일에 아래 의미의 4줄 이하 블록만 추가한다.

```markdown
### AI 연구 실행 계약

Standard 이상 연구는 `docs/research/AI-OPERATING-CONTRACT.md`를 따르고 실행 전
`scripts/verify_research_run_manifest.py`로 run manifest를 검증한다.
```

- [ ] **Step 4: 카탈로그·상위 설계 연결**

`docs/research/catalog.json`에 `ai-operating-contract-v1`, status `operational`, contract/schema/example,
validator 경로, 구현 commit을 기록한다. `docs/research/README.md`의 “지금 할 일”은 AI contract
완료 → R1 Mac mini runtime foundation 순서를 보여준다. 상위 RBA 설계와 `specs/next-session.md`에는
contract가 R1의 선행 gate라는 한 문단을 추가한다.

- [ ] **Step 5: GREEN 확인**

Run:

```bash
uv run pytest -q tests/test_ai_operating_contract.py tests/test_verify_research_run_manifest.py
python3 -m json.tool docs/research/catalog.json >/dev/null
git diff --check
```

Expected: focused tests pass, JSON valid, diff check exit 0.

- [ ] **Step 6: Task 5 커밋**

```bash
git add AGENTS.md CLAUDE.md docs/research docs/superpowers/specs/2026-07-27-rba-research-system-v1-design.md specs/next-session.md tests/test_ai_operating_contract.py
git commit -m "docs: AI 운영 계약을 연구 진입점에 연결"
```

---

### Task 6: 전체 회귀·보안 감사·완료 보고

**Files:**
- Create: `docs/handoff-prompts/2026-07-27-ai-operating-contract-report.md`
- Modify: `.claude/donts-audit.md`

**Interfaces:**
- Consumes: Tasks 1~5 전체 구현.
- Produces: 검증 증거, 실제 model/permission, 다음 R1 허용 상태를 기록한 완료 보고.

- [ ] **Step 1: focused·전체 회귀 실행**

Run:

```bash
uv run pytest -q tests/test_ai_operating_contract.py tests/test_verify_research_run_manifest.py
uv run pytest -q
python3 -m compileall -q scripts/verify_research_run_manifest.py
python3 -m json.tool docs/research/RUN-MANIFEST.schema.json >/dev/null
python3 -m json.tool docs/research/RUN-MANIFEST.example.json >/dev/null
python3 -m json.tool docs/research/catalog.json >/dev/null
git diff --check
```

Expected: all commands exit 0.

- [ ] **Step 2: 민감 필드·권한 약화 정적 감사**

Run:

```bash
rg -n -i '"(password|api_key|webhook|cookie|signed_url|secret)"\s*:' \
  docs/research scripts/verify_research_run_manifest.py tests/test_verify_research_run_manifest.py
```

Expected: only negative test fixtures; production example and schema contain zero secret fields.

Run:

```bash
rg -n 'P4는 항상 별도 Owner 승인|P0~P2|p3_authorization_missing|p4_authorization_missing' \
  docs/research scripts/verify_research_run_manifest.py
```

Expected: contract and validator both expose the agreed gates.

- [ ] **Step 3: 완료 보고 작성**

보고서는 다음 verdict와 항목을 사용한다.

```markdown
# AI 연구 운영 계약 완료 보고

## 판정

AI_OPERATING_CONTRACT_V1_VERIFIED

## 권한

- P0~P2: 승인된 package에서 자동
- P3: exact target·rollback·canary + package 승인
- P4: 별도 Owner 승인

## 모델 provenance

- requested/actual model
- requested/actual reasoning
- surface와 fallback 여부

## 검증

- focused/전체 pytest
- JSON parse
- CLI start/final·schema-only
- secret field·permission regression
- git diff/status/upstream

## 다음

R1 Mac mini research runtime foundation 계획 작성 허용
```

실제 실행에서 확인한 test count, commit, branch, upstream, tracked/untracked 상태를 채운다.

- [ ] **Step 4: donts audit 기록**

`.claude/donts-audit.md`에 “권한 자동화는 P0~P2 범위와 manifest provenance를 함께 고정해야 하며,
model requested/actual을 구분한다”는 한 줄을 추가한다.

- [ ] **Step 5: Task 6 커밋·push**

```bash
git add docs/handoff-prompts/2026-07-27-ai-operating-contract-report.md .claude/donts-audit.md
git commit -m "docs: AI 연구 운영 계약 검증 보고"
git push -u origin codex/research-catalog-20260727
```

- [ ] **Step 6: 최종 동기화 확인**

Run:

```bash
test "$(git rev-parse HEAD)" = "$(git rev-parse @{u})"
test -z "$(git status --porcelain)"
```

Expected: both commands exit 0. Main merge, production deploy, Mac mini 변경은 0.
