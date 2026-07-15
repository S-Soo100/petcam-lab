# Cross-Repo Runtime Handoff Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **상태:** 구현·검증 완료, commit 승인 대기. handoff 전용 45 tests와 전체 381 tests가 통과했고, nightly bootstrap은 의도대로 `HANDOFF_FAIL code=artifact_untracked`다. 아래 commit 단계는 아직 실행하지 않았다.

**Goal:** 다른 에이전트·레포·머신으로 넘기는 작업이 실제 파일, Git commit, 실행 레포, runtime host 증거를 갖췄는지 기계적으로 검증하고 잘못된 운영 SOT를 바로잡는다.

**Architecture:** 표준 라이브러리만 쓰는 fail-closed CLI가 handoff Markdown의 제한된 front matter를 파싱하고, 실제 Git repo·tracked artifact·HEAD SHA·runtime metadata를 검증한다. AGENTS/CLAUDE 규칙과 handoff template이 검증 실행을 의무화하고, SOT는 worker 상태를 planned/installed/enabled/verified 증거 단계로 기록한다.

**Tech Stack:** Python 3.12 standard library, pytest, Git CLI, Markdown.

## Global Constraints

- 설계 정본은 `docs/superpowers/specs/2026-07-16-cross-repo-runtime-handoff-guard-design.md`다.
- 모든 Python 명령은 `uv run python` 또는 `uv run pytest`를 사용한다. bare `python`, `pip`는 금지한다.
- PyYAML 등 신규 dependency를 추가하지 않는다.
- validator는 `--allow-untracked`, `--force`, `--skip-git-check` 우회 옵션을 제공하지 않는다.
- plan/design은 절대경로·일반파일·execution repo 내부·tracked·지정 commit 포함·clean이어야 한다.
- `runtime_kind != none`이면 runtime host와 label이 필수다.
- `runtime_kind == none`이면 runtime host/label을 허용하지 않는다.
- 일반 stdout에는 전체 local path, Git stderr, manifest 임의 문자열을 노출하지 않는다.
- Claude가 구현 중인 `/Users/baek/petcam-nightly-reporter/reporter/*`와 launchd installer를 수정하지 않는다.
- production DB, SSH, LaunchAgent 상태를 변경하지 않는다.
- 현재 nightly VLM plan/design은 untracked이므로 구현 직후 bootstrap 검증은 `artifact_untracked`가 정답이다.
- commit/push는 사용자 명시 승인 전 실행하지 않는다. 아래 commit 단계는 승인 경계에서만 실행한다.

## File Structure

- Create: `scripts/verify_agent_handoff.py` — front matter, path, Git, runtime 계약과 CLI.
- Create: `tests/test_verify_agent_handoff.py` — 실제 임시 Git repo 기반 TDD.
- Create: `docs/handoff-prompts/_agent-task-handoff-template.md` — 앞으로 복사할 표준 manifest/template.
- Modify: `AGENTS.md` — 모든 에이전트 공통 handoff gate.
- Modify: `CLAUDE.md` — Claude 자동 로드 cross-repo/runtime gate.
- Modify: `specs/next-session.md` — 잘못된 Mac mini VLM host attribution 정정.
- Modify: `.claude/donts-audit.md` — 이번 사고와 재발 방지 기록.
- Modify: `docs/superpowers/plans/2026-07-16-vlm-single-host-operations-hardening.md` — bootstrap `artifact_untracked` 상태 설명만 추가.
- Modify: `docs/superpowers/specs/2026-07-16-cross-repo-runtime-handoff-guard-design.md` — 구현 완료 상태 반영.

---

### Task 1: 제한된 front matter parser와 schema

**Files:**
- Create: `scripts/verify_agent_handoff.py`
- Create: `tests/test_verify_agent_handoff.py`

**Interfaces:**
- Produces: `HandoffError(code: str)`
- Produces: `HandoffManifest`
- Produces: `parse_manifest(path: Path) -> HandoffManifest`

- [ ] **Step 1: parser RED tests 작성**

다음 test helper와 cases를 작성한다.

```python
from pathlib import Path

import pytest

from scripts.verify_agent_handoff import HandoffError, parse_manifest


def write_manifest(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def valid_manifest_text(
    *, overrides: dict[str, str] | None = None, extra_lines: list[str] | None = None
) -> str:
    values = {
        "handoff_version": "1",
        "task_id": "test-task",
        "execution_repo": "/tmp/test-repo",
        "plan_path": "/tmp/test-repo/docs/plan.md",
        "design_path": "/tmp/test-repo/specs/design.md",
        "commit_sha": "0" * 40,
        "implementation_host": "dev-mac.local",
        "runtime_kind": "none",
    }
    values.update(overrides or {})
    lines = ["---", *(f"{key}: {value}" for key, value in values.items())]
    lines.extend(extra_lines or [])
    lines.extend(["---", "# Handoff"])
    return "\n".join(lines) + "\n"


def test_parse_manifest_rejects_missing_front_matter(tmp_path: Path) -> None:
    path = write_manifest(tmp_path / "handoff.md", "# no header\n")
    with pytest.raises(HandoffError, match="manifest_invalid"):
        parse_manifest(path)


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("runtime_kind", "mystery", "invalid_runtime_kind"),
        ("commit_sha", "short", "invalid_commit_sha"),
    ],
)
def test_parse_manifest_rejects_invalid_fields(
    tmp_path: Path, field: str, value: str, code: str
) -> None:
    text = valid_manifest_text(overrides={field: value})
    path = write_manifest(tmp_path / "handoff.md", text)
    with pytest.raises(HandoffError, match=code):
        parse_manifest(path)


def test_parse_manifest_rejects_unknown_and_duplicate_keys(tmp_path: Path) -> None:
    for line, code in (("mystery: value", "unexpected_field"), ("task_id: again", "manifest_invalid")):
        path = write_manifest(
            tmp_path / f"{code}.md", valid_manifest_text(extra_lines=[line])
        )
        with pytest.raises(HandoffError, match=code):
            parse_manifest(path)
```

별도 cases:

- 파일 없음 → `manifest_missing`
- `handoff_version != 1` → `unsupported_version`
- 필수 field 누락/빈 값 → `required_field_missing`
- nested YAML/list/quoted multiline → `manifest_invalid`
- key 중복 → `manifest_invalid`
- runtime none + host/label → `runtime_field_forbidden`
- launchagent + host 누락 → `runtime_host_missing`
- launchagent + label 누락 → `runtime_label_missing`
- implementation host에 newline/control character → `manifest_invalid`

- [ ] **Step 2: RED 확인**

```bash
uv run pytest tests/test_verify_agent_handoff.py -q
```

Expected: `ModuleNotFoundError: scripts.verify_agent_handoff`.

- [ ] **Step 3: parser 최소 구현**

`scripts/verify_agent_handoff.py`에 다음 구조를 구현한다.

```python
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


ALLOWED_KEYS = frozenset({
    "handoff_version",
    "task_id",
    "execution_repo",
    "plan_path",
    "design_path",
    "commit_sha",
    "implementation_host",
    "runtime_kind",
    "runtime_host",
    "runtime_label",
})
RUNTIME_KINDS = frozenset({
    "none", "launchagent", "server", "scheduled-job", "mobile-build"
})
SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")
SHA40 = re.compile(r"^[0-9a-f]{40}$")


class HandoffError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class HandoffManifest:
    task_id: str
    execution_repo: Path
    plan_path: Path
    design_path: Path
    commit_sha: str
    implementation_host: str
    runtime_kind: str
    runtime_host: str | None
    runtime_label: str | None
```

parser 규칙:

1. 첫 줄과 닫는 줄이 정확히 `---`
2. header 각 nonblank 줄은 `key: value` 하나
3. `split(":", 1)` 후 key/value trim
4. 중복·unknown key·빈 key/value 거부
5. 모든 path는 `Path(value).is_absolute()` 필요
6. task/host/label은 `SAFE_NAME`
7. SHA는 `SHA40`
8. runtime conditional fields 검사

exception 문자열에는 path/value를 넣지 않고 code만 넣는다.

- [ ] **Step 4: parser GREEN 확인**

```bash
uv run pytest tests/test_verify_agent_handoff.py -q
```

Expected: parser tests pass. Git/path validation tests는 아직 작성하지 않는다.

- [ ] **Step 5: 승인된 경우에만 첫 commit**

```bash
git add scripts/verify_agent_handoff.py tests/test_verify_agent_handoff.py
git commit -m "feat: 에이전트 handoff manifest 검증 기반 추가"
```

사용자 commit 승인이 없으면 stage/commit하지 않고 다음 task로 진행한다.

---

### Task 2: path·Git visibility·runtime validator

**Files:**
- Modify: `scripts/verify_agent_handoff.py`
- Modify: `tests/test_verify_agent_handoff.py`

**Interfaces:**
- Consumes: `HandoffManifest`, `HandoffError`, `parse_manifest`
- Produces: `HandoffSummary`
- Produces: `validate_handoff(path: Path, *, runner=subprocess.run) -> HandoffSummary`

- [ ] **Step 1: 실제 임시 Git repo helper 작성**

Git을 mock하지 않고 다음 helper를 test 파일에 추가한다.

```python
import subprocess


def git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def committed_repo(tmp_path: Path) -> tuple[Path, Path, Path, str]:
    repo = tmp_path / "worker-repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Test")
    plan = repo / "docs" / "plan.md"
    design = repo / "specs" / "design.md"
    plan.parent.mkdir()
    design.parent.mkdir()
    plan.write_text("# Plan\n", encoding="utf-8")
    design.write_text("# Design\n", encoding="utf-8")
    git(repo, "add", "docs/plan.md", "specs/design.md")
    git(repo, "commit", "-m", "test fixture")
    return repo, plan, design, git(repo, "rev-parse", "HEAD")


def repo_manifest_text(
    repo: Path,
    plan: Path,
    design: Path,
    sha: str,
    *,
    runtime_kind: str = "none",
    runtime_host: str | None = None,
    runtime_label: str | None = None,
) -> str:
    overrides = {
        "execution_repo": str(repo),
        "plan_path": str(plan),
        "design_path": str(design),
        "commit_sha": sha,
        "runtime_kind": runtime_kind,
    }
    if runtime_host is not None:
        overrides["runtime_host"] = runtime_host
    if runtime_label is not None:
        overrides["runtime_label"] = runtime_label
    return valid_manifest_text(overrides=overrides)
```

- [ ] **Step 2: validator RED tests 작성**

최소 다음 tests를 각각 한 behavior로 작성한다.

```python
def test_validate_handoff_accepts_clean_tracked_artifacts(tmp_path: Path) -> None:
    repo, plan, design, sha = committed_repo(tmp_path)
    manifest = write_manifest(
        tmp_path / "handoff.md",
        repo_manifest_text(
            repo, plan, design, sha,
            runtime_kind="launchagent",
            runtime_host="mac-mini.local",
            runtime_label="com.petcam.worker",
        ),
    )
    summary = validate_handoff(manifest)
    assert summary.commit_short == sha[:8]
    assert summary.repo_name == "worker-repo"
    assert summary.runtime == "launchagent@mac-mini.local"
```

Error cases and expected codes:

- missing repo → `repo_missing`
- repo path가 root 하위 directory → `repo_not_git_root`
- repo path 자체 symlink → `repo_not_git_root`
- missing plan/design → `plan_missing` / `design_missing`
- relative path → parser `manifest_invalid`
- plan/design symlink → `artifact_symlink`
- realpath가 repo 밖 → `artifact_outside_repo`
- untracked → `artifact_untracked`
- staged-only → `artifact_untracked`
- 지정 commit에 artifact 없음 → `artifact_not_in_commit`
- HEAD != SHA → `head_mismatch`
- tracked artifact 수정 → `artifact_dirty`
- Git timeout/nonstandard error → `git_probe_failed`

- [ ] **Step 3: RED 확인**

```bash
uv run pytest tests/test_verify_agent_handoff.py -q
```

Expected: `validate_handoff` import/behavior failures.

- [ ] **Step 4: Git runner와 summary 최소 구현**

```python
import subprocess
from collections.abc import Callable, Sequence


@dataclass(frozen=True, slots=True)
class HandoffSummary:
    task_id: str
    repo_name: str
    commit_short: str
    runtime: str


Runner = Callable[..., subprocess.CompletedProcess[str]]


def _git(repo: Path, args: Sequence[str], runner: Runner) -> subprocess.CompletedProcess[str]:
    try:
        return runner(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise HandoffError("git_probe_failed") from exc
```

구현 순서:

1. repo 입력이 symlink가 아닌지 확인
2. strict resolve 후 입력 절대경로와 동일한지 확인
3. `git rev-parse --show-toplevel`과 repo exact 비교
4. artifact final component와 repo→artifact 모든 path component symlink 검사
5. `resolved.relative_to(repo)`로 containment 검사
6. `git ls-files --error-unmatch -- docs/plan.md`
7. `git cat-file -e 0123456789abcdef0123456789abcdef01234567:docs/plan.md`와 같은 commit-colon-path 형식
8. `git rev-parse HEAD`
9. `git status --porcelain -- docs/plan.md`

Git command 실패를 무조건 한 code로 뭉개지 않는다.

- `ls-files` nonzero → `artifact_untracked`
- `cat-file` nonzero → `artifact_not_in_commit`
- 그 외 required probe nonzero → `git_probe_failed`

- [ ] **Step 5: GREEN 확인**

```bash
uv run pytest tests/test_verify_agent_handoff.py -q
```

Expected: all parser/path/Git/runtime tests pass.

- [ ] **Step 6: 승인된 경우에만 commit**

```bash
git add scripts/verify_agent_handoff.py tests/test_verify_agent_handoff.py
git commit -m "feat: handoff 경로와 Git 가시성 검증"
```

---

### Task 3: 안전한 CLI 출력과 exit contract

**Files:**
- Modify: `scripts/verify_agent_handoff.py`
- Modify: `tests/test_verify_agent_handoff.py`

**Interfaces:**
- Consumes: `validate_handoff`
- Produces: `main(argv: Sequence[str] | None = None) -> int`

- [ ] **Step 1: CLI RED tests 작성**

```python
def test_main_prints_only_allowlisted_failure_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    secret_path = tmp_path / "Users" / "private-name" / "missing.md"
    rc = main(["--manifest", str(secret_path)])
    captured = capsys.readouterr()
    assert rc == 1
    assert captured.out == "HANDOFF_FAIL code=manifest_missing\n"
    assert captured.err == ""
    assert "private-name" not in captured.out


def test_main_prints_safe_success_summary(tmp_path: Path, capsys) -> None:
    repo, plan, design, sha = committed_repo(tmp_path)
    manifest = write_manifest(
        tmp_path / "handoff.md",
        repo_manifest_text(repo, plan, design, sha),
    )
    assert main(["--manifest", str(manifest)]) == 0
    assert capsys.readouterr().out == (
        f"HANDOFF_OK task=test-task repo=worker-repo "
        f"commit={sha[:8]} runtime=none\n"
    )
```

추가 tests:

- Git stderr에 home path가 있어도 출력 0
- manifest task/host control characters parser 거부
- unknown CLI option은 argparse usage만 stderr, manifest 값 미노출
- `--allow-untracked`, `--force`, `--skip-git-check` 모두 argparse error

- [ ] **Step 2: RED 확인**

```bash
uv run pytest tests/test_verify_agent_handoff.py -q
```

Expected: `main` missing/failing.

- [ ] **Step 3: CLI 최소 구현**

```python
import argparse
from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify an agent handoff manifest")
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        summary = validate_handoff(args.manifest)
    except HandoffError as exc:
        print(f"HANDOFF_FAIL code={exc.code}")
        return 1
    print(
        f"HANDOFF_OK task={summary.task_id} repo={summary.repo_name} "
        f"commit={summary.commit_short} runtime={summary.runtime}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: CLI GREEN 확인**

```bash
uv run pytest tests/test_verify_agent_handoff.py -q
uv run python scripts/verify_agent_handoff.py --help >/dev/null
```

Expected: tests pass, help exit 0.

- [ ] **Step 5: 승인된 경우에만 commit**

```bash
git add scripts/verify_agent_handoff.py tests/test_verify_agent_handoff.py
git commit -m "feat: 안전한 handoff preflight CLI 제공"
```

---

### Task 4: 공통 handoff template과 agent 강제 규칙

**Files:**
- Create: `docs/handoff-prompts/_agent-task-handoff-template.md`
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: CLI command from Task 3
- Produces: all-agent process contract

- [ ] **Step 1: 문서 계약 test RED 작성**

`tests/test_verify_agent_handoff.py`에 static contract tests를 추가한다.

```python
def test_agent_rules_require_handoff_validator() -> None:
    agents = Path("AGENTS.md").read_text(encoding="utf-8")
    claude = Path("CLAUDE.md").read_text(encoding="utf-8")
    required = (
        "scripts/verify_agent_handoff.py",
        "execution_repo",
        "implementation_host",
        "runtime_host",
        "HANDOFF_OK",
    )
    for marker in required:
        assert marker in agents
        assert marker in claude


def test_handoff_template_contains_required_manifest_fields() -> None:
    template = Path("docs/handoff-prompts/_agent-task-handoff-template.md").read_text(
        encoding="utf-8"
    )
    for field in (
        "handoff_version:", "task_id:", "execution_repo:", "plan_path:",
        "design_path:", "commit_sha:", "implementation_host:", "runtime_kind:",
        "runtime_host:", "runtime_label:",
    ):
        assert field in template
    assert "--allow-untracked" not in template
```

- [ ] **Step 2: RED 확인**

```bash
uv run pytest tests/test_verify_agent_handoff.py -q
```

Expected: missing template/rule markers.

- [ ] **Step 3: template 작성**

template은 실제 값으로 교체해야 하는 예시임을 명시하고 다음 실행 순서를 포함한다.

```markdown
1. plan/design 사용자 검토
2. commit/push 사용자 승인
3. plan/design tracked commit 확인
4. manifest에 `git rev-parse HEAD`의 40자리 SHA 기록
5. `uv run python scripts/verify_agent_handoff.py --manifest /Users/baek/petcam-lab/docs/superpowers/plans/2026-07-16-vlm-single-host-operations-hardening.md`
6. `HANDOFF_OK` 전문과 manifest 절대경로를 수신 agent에게 전달
```

runtime이 없는 task는 `runtime_kind: none`이고 host/label 두 줄을 제거하도록 한다. runtime이 있으면 두 줄을 실제 값으로 채운다.

- [ ] **Step 4: AGENTS.md 규칙 추가**

`## 5. 에이전트 간 공통 원칙` 시작부에 `### Cross-repo·runtime handoff gate`를 추가한다.

필수 문구:

- 상대경로만 전달 금지
- plan/design tracked commit 필수
- validator `HANDOFF_OK` 전 구현 명령 금지
- implementation host와 runtime host 별도 기록
- runtime 완료 주장은 목표 host evidence 필요
- 파일이 없을 때 추측 구현 금지는 올바른 fail-closed

- [ ] **Step 5: CLAUDE.md 규칙 추가**

`### 멀티 머신 운영` 바로 아래에 같은 계약을 Claude용 실행 순서로 추가한다.

Claude가 다른 repo 작업 지시를 받으면:

1. manifest 절대경로 확인
2. validator 실행
3. `execution_repo`로 `cd`
4. HEAD SHA 재확인
5. 구현 시작

- [ ] **Step 6: GREEN 확인**

```bash
uv run pytest tests/test_verify_agent_handoff.py -q
```

- [ ] **Step 7: 승인된 경우에만 commit**

```bash
git add AGENTS.md CLAUDE.md docs/handoff-prompts/_agent-task-handoff-template.md tests/test_verify_agent_handoff.py
git commit -m "docs: cross-repo handoff 검증 규칙 고정"
```

---

### Task 5: VLM host 오류 SOT 정정과 bootstrap 기록

**Files:**
- Modify: `specs/next-session.md`
- Modify: `.claude/donts-audit.md`
- Modify: `docs/superpowers/plans/2026-07-16-vlm-single-host-operations-hardening.md`
- Test: `tests/test_verify_agent_handoff.py`

**Interfaces:**
- Produces: evidence-based worker state terminology
- Produces: current handoff bootstrap status

- [ ] **Step 1: SOT RED test 작성**

```python
def test_current_sot_does_not_claim_mac_mini_vlm_candidate_verified() -> None:
    sot = Path("specs/next-session.md").read_text(encoding="utf-8")
    assert "야간 VLM 후보 shadow — host attribution 정정" in sot
    assert "정규 candidate LaunchAgent는 MacBook에서 발견" in sot
    assert "Mac mini verified 아님" in sot
    assert "Mac mini의 `com.petcam.vlm-candidate-worker`가" not in sot


def test_vlm_handoff_records_untracked_bootstrap_boundary() -> None:
    handoff = Path(
        "docs/superpowers/plans/2026-07-16-vlm-single-host-operations-hardening.md"
    ).read_text(encoding="utf-8")
    assert "artifact_untracked" in handoff
    assert "HANDOFF_OK" in handoff
    assert "commit/push 승인 후" in handoff
```

- [ ] **Step 2: RED 확인**

```bash
uv run pytest tests/test_verify_agent_handoff.py -q
```

Expected: old SOT wording and missing bootstrap record.

- [ ] **Step 3: next-session VLM block 교체**

기존 VLM block의 결과 사실은 보존하되 host attribution을 다음 계약으로 고친다.

```markdown
> **야간 VLM 후보 shadow — host attribution 정정, single-host hardening 중:** 2026-07-16 실측에서 정규 `com.petcam.vlm-candidate-worker` LaunchAgent는 Mac mini가 아니라 MacBook에서 발견됐고, Mac mini에는 정규 candidate agent가 없었다. 기존 8건 성공 결과와 exact Sonnet 5·구독 비용 0원 기록은 유효하지만 “Mac mini 운영 중” 주장은 철회한다. Mac mini historical backfill worker가 정규 failed job을 처리한 정황은 코드와 시간순서에 기반한 추론이며 producer host audit로 재검증한다. 현재 상태는 `planned`: Mac mini 단일-host guard·regular/backfill queue 격리·Slack 관측을 구현 중이고 **Mac mini verified 아님**이다. installed/enabled/verified 전환은 목표 host의 hostname·launchctl·한-window canary 증거 후에만 기록한다.
```

- [ ] **Step 4: VLM handoff bootstrap 경계 추가**

handoff 진입 문서 상단에 다음 경고를 추가한다.

```markdown
> Bootstrap 상태: nightly의 plan/design이 아직 untracked라 새 validator 기준 `artifact_untracked`가 정상이다. 이 문서는 이미 시작된 사고 복구 handoff이며 `HANDOFF_OK`로 소급 가장하지 않는다. nightly plan/design commit/push 승인 후 manifest를 만들고 `HANDOFF_OK`를 확인해야 다음 cross-session handoff가 가능하다.
```

- [ ] **Step 5: donts audit 기록**

`.claude/donts-audit.md` 최상단 최신 기록에 다음 사실을 한 줄로 남긴다.

- 잘못: 존재하지 않는 현재-repo 상대경로 전달, runtime host 실측 없이 Mac mini 운영 주장
- 원인: execution repo/commit/runtime host의 기계 검증 부재
- 재발 방지: tracked manifest + validator + planned/installed/enabled/verified 증거 단계
- 금지: untracked plan handoff, producer host 추측

- [ ] **Step 6: GREEN 확인**

```bash
uv run pytest tests/test_verify_agent_handoff.py -q
```

- [ ] **Step 7: 승인된 경우에만 commit**

```bash
git add specs/next-session.md .claude/donts-audit.md \
  docs/superpowers/plans/2026-07-16-vlm-single-host-operations-hardening.md \
  tests/test_verify_agent_handoff.py
git commit -m "docs: VLM 실행 호스트 오류와 handoff 경계 정정"
```

---

### Task 6: Bootstrap negative proof와 전체 검증

**Files:**
- Modify: `docs/superpowers/specs/2026-07-16-cross-repo-runtime-handoff-guard-design.md`
- Modify: `docs/superpowers/plans/2026-07-16-cross-repo-runtime-handoff-guard.md`
- No production code changes beyond prior tasks

**Interfaces:**
- Consumes: validator CLI
- Produces: verified implementation report and honest bootstrap failure

- [ ] **Step 1: 임시 manifest로 현재 nightly artifact 검증**

현재 nightly HEAD를 읽어 임시 파일에 manifest를 만들되 repo 파일을 수정하지 않는다.

```bash
NIGHTLY_HEAD="$(git -C /Users/baek/petcam-nightly-reporter rev-parse HEAD)"
MANIFEST="$(mktemp /tmp/petcam-handoff.XXXXXX)"
cat >"$MANIFEST" <<EOF
---
handoff_version: 1
task_id: vlm-single-host-operations-hardening
execution_repo: /Users/baek/petcam-nightly-reporter
plan_path: /Users/baek/petcam-nightly-reporter/docs/superpowers/plans/2026-07-16-vlm-single-host-operations-hardening.md
design_path: /Users/baek/petcam-nightly-reporter/specs/2026-07-16-vlm-single-host-operations-hardening-design.md
commit_sha: $NIGHTLY_HEAD
implementation_host: BaekBook-Pro-14-M5.local
runtime_kind: launchagent
runtime_host: baeg-endeuui-Macmini.local
runtime_label: com.petcam.vlm-candidate-worker
---
EOF
uv run python scripts/verify_agent_handoff.py --manifest "$MANIFEST"
RC=$?
rm -f "$MANIFEST"
test "$RC" -eq 1
```

Expected exact stdout before removal:

```text
HANDOFF_FAIL code=artifact_untracked
```

이 실패를 고치려고 nightly 파일을 stage/commit하지 않는다.

- [ ] **Step 2: targeted tests**

```bash
uv run pytest tests/test_verify_agent_handoff.py -q
```

Expected: all handoff guard tests pass.

- [ ] **Step 3: full petcam-lab tests**

```bash
uv run pytest -q
```

Expected: all tests pass.

- [ ] **Step 4: syntax·whitespace·scope 검증**

```bash
uv run python -m py_compile scripts/verify_agent_handoff.py
git diff --check
git diff --stat
git status --short
```

Expected:

- syntax clean
- whitespace clean
- 변경은 설계의 Create/Modify 목록뿐
- nightly `reporter/*`, installer, DB, LaunchAgent 변경 0

- [ ] **Step 5: unsafe bypass와 stale claim 검색**

```bash
rg -n -- "--allow-untracked|--skip-git-check|--force" \
  scripts/verify_agent_handoff.py docs/handoff-prompts/_agent-task-handoff-template.md
rg -n "Mac mini의 `com.petcam.vlm-candidate-worker`가" specs/next-session.md
```

Expected: both commands return no matches. `--force` search가 문서의 금지 설명까지 잡으면 production CLI option 정의가 없는지 argparse code로 직접 확인한다.

- [ ] **Step 6: spec coverage self-review**

다음을 한 줄씩 결과 보고에 대응시킨다.

- path existence/repo containment
- tracked/commit/HEAD/dirty
- runtime conditional metadata
- safe output
- agent rules/template
- SOT correction
- bootstrap negative proof
- no nightly worker/runtime mutation

- [ ] **Step 7: 설계·계획 상태 갱신**

설계와 계획 상단 상태를 `구현 완료·commit 승인 대기`로 바꾸고 실제 test count와 bootstrap 결과를 기록한다. `HANDOFF_OK`라고 쓰지 않는다.

- [ ] **Step 8: 완료 보고 후 commit 승인 대기**

보고 형식:

```text
완료 보고 — Cross-Repo Runtime Handoff Guard

validator: 구현 / N tests pass
rules: AGENTS + CLAUDE 반영
SOT: Mac mini 오기록 정정
bootstrap: HANDOFF_FAIL artifact_untracked (의도된 정직한 실패)
nightly worker/runtime 변경: 0
commit/push: 미실행

다음 승인 경계:
1. petcam-lab guard commit/push
2. nightly plan/design commit/push
3. 실제 SHA manifest 생성
4. HANDOFF_OK 확인 후에만 다음 handoff
```

여기서 멈춘다.

## Post-Approval Commit Order

사용자가 commit/push를 승인하면 다음 순서를 지킨다.

1. petcam-lab guard 변경을 명시 add·commit·push
2. nightly에서 Claude 구현 작업과 겹치지 않는지 `git status --short`로 확인
3. nightly plan/design의 소유권과 구현 diff를 함께 검토
4. 승인 범위만 nightly commit·push
5. nightly 새 HEAD로 실제 handoff manifest 생성
6. petcam-lab validator `HANDOFF_OK`
7. 그 성공 전문을 다음 에이전트 메시지에 포함

두 repo를 한 commit으로 취급하지 않는다.
