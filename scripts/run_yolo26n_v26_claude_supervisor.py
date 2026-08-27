"""Run a fail-closed, read-only Claude review of the v2.6 human-GT gate."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any
import zipfile


BLIND_IMAGE_MEMBER = re.compile(r"^images/frame_[0-9a-f]{24}\.jpg$")


class ContractError(ValueError):
    """Raised when a frozen artifact no longer matches its contract."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_contract(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    required = {
        "expected_status",
        "primary_zip",
        "primary_sha256",
        "primary_count",
        "double_review_zip",
        "double_review_sha256",
        "double_review_count",
        "review_index",
        "review_index_sha256",
        "completion_manifest",
        "human_gt_inbox",
        "prompt_doc",
        "repo",
        "attempt_root",
    }
    missing = sorted(required - payload.keys())
    if missing:
        raise ContractError(f"contract_missing_fields:{','.join(missing)}")
    return payload


def _require_sha(path: Path, expected: str, reason: str) -> None:
    if not path.is_file():
        raise ContractError(f"{reason}_missing")
    if _sha256(path) != expected:
        raise ContractError(f"{reason}_sha256_mismatch")


def _verify_zip(path: Path, expected_count: int, reason: str) -> int:
    try:
        with zipfile.ZipFile(path) as archive:
            if archive.testzip() is not None:
                raise ContractError(f"{reason}_crc_error")
            image_members = [
                name for name in archive.namelist() if BLIND_IMAGE_MEMBER.fullmatch(name)
            ]
    except (OSError, zipfile.BadZipFile) as exc:
        raise ContractError(f"{reason}_invalid_zip") from exc
    if len(image_members) != expected_count:
        raise ContractError(f"{reason}_member_count_mismatch")
    if len(image_members) != len(set(image_members)):
        raise ContractError(f"{reason}_duplicate_member")
    return len(image_members)


def verify_contract(contract: dict[str, Any]) -> dict[str, object]:
    completion = Path(str(contract["completion_manifest"]))
    if not completion.is_file():
        raise ContractError("completion_manifest_missing")
    completion_payload = json.loads(completion.read_text())
    if completion_payload.get("status") != contract["expected_status"]:
        raise ContractError("completion_status_mismatch")

    primary = Path(str(contract["primary_zip"]))
    double_review = Path(str(contract["double_review_zip"]))
    review_index = Path(str(contract["review_index"]))
    _require_sha(primary, str(contract["primary_sha256"]), "primary_zip")
    _require_sha(
        double_review,
        str(contract["double_review_sha256"]),
        "double_review_zip",
    )
    _require_sha(
        review_index,
        str(contract["review_index_sha256"]),
        "review_index",
    )
    primary_count = _verify_zip(
        primary,
        int(contract["primary_count"]),
        "primary_zip",
    )
    double_review_count = _verify_zip(
        double_review,
        int(contract["double_review_count"]),
        "double_review_zip",
    )

    inbox = Path(str(contract["human_gt_inbox"]))
    expected_exports = (
        inbox / "primary-cvat-export.zip",
        inbox / "double-review-cvat-export.zip",
    )
    present = [path.is_file() and path.stat().st_size > 0 for path in expected_exports]
    # File presence is only an inbox signal.  CVAT schema, bbox, negative and
    # adjudication checks happen in the separate deterministic GT validator.
    human_export_state = (
        "PRESENT_UNVALIDATED" if all(present) else "PARTIAL" if any(present) else "WAITING"
    )
    return {
        "double_review_count": double_review_count,
        "human_gt_validated": False,
        "human_export_state": human_export_state,
        "primary_count": primary_count,
        "status": "SUPERVISOR_PREFLIGHT_OK",
    }


def build_claude_command(executable: str, contract: dict[str, Any]) -> list[str]:
    repo = str(Path(str(contract["repo"])).resolve())
    attempt_root = str(Path(str(contract["attempt_root"])).resolve())
    return [
        executable,
        "-p",
        "--safe-mode",
        "--no-chrome",
        "--permission-mode",
        "dontAsk",
        "--allowedTools",
        "Read,Glob,Grep",
        "--disallowedTools",
        "Write,Edit,NotebookEdit,Bash,WebSearch,WebFetch",
        "--add-dir",
        repo,
        attempt_root,
        "--model",
        "fable",
        "--effort",
        "high",
        "--output-format",
        "json",
        "--no-session-persistence",
        "--name",
        "YOLO26n v2.6 사람 GT 검수 감독",
    ]


def _prompt_text(contract: dict[str, Any], preflight: dict[str, object]) -> str:
    prompt_doc = Path(str(contract["prompt_doc"]))
    text = prompt_doc.read_text()
    match = re.search(r"```text\n([\s\S]*?)\n```", text)
    if match is None:
        raise ContractError("prompt_block_missing")
    return (
        match.group(1)
        + "\n\n## 이번 실행의 deterministic preflight aggregate\n\n"
        + json.dumps(preflight, sort_keys=True)
        + "\n\nWrite/Edit/Bash는 도구 수준에서 차단돼 있다. 신규 파일을 만들지 말고 "
        "읽기 전용 확인 결과만 응답해."
    )


def _run_claude(
    *,
    command: list[str],
    prompt: str,
    output_root: Path,
) -> int:
    output_root.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    run_dir = output_root / run_id
    run_dir.mkdir()
    result = subprocess.run(
        command,
        input=prompt,
        check=False,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    record = {
        "completed_at": datetime.now(UTC).isoformat(),
        "exit_code": result.returncode,
        "stderr": result.stderr[-4000:],
        "stdout": result.stdout,
    }
    result_path = run_dir / "claude-result.private.json"
    result_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    latest_path = output_root / "latest-result-path.txt"
    latest_path.write_text(str(result_path) + "\n")
    if result.returncode != 0:
        print(
            json.dumps(
                {
                    "status": "CLAUDE_SUPERVISOR_FAILED",
                    "exit_code": result.returncode,
                    "result_path": str(result_path),
                },
                ensure_ascii=False,
            )
        )
        return 1
    try:
        response = json.loads(result.stdout)
        message = str(response.get("result", ""))
    except json.JSONDecodeError:
        message = result.stdout
    if "DONT_NOTIFY" in message:
        print("DONT_NOTIFY")
    else:
        print(
            json.dumps(
                {
                    "status": "CLAUDE_SUPERVISOR_REPORTED",
                    "result_path": str(result_path),
                },
                ensure_ascii=False,
            )
        )
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--print-claude-command", action="store_true")
    parser.add_argument("--claude-executable", default="claude")
    parser.add_argument("--output-root", type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        contract = _load_contract(args.contract)
        preflight = verify_contract(contract)
    except (ContractError, json.JSONDecodeError, OSError) as exc:
        reason = str(exc)
        print(json.dumps({"reason": reason, "status": "SUPERVISOR_FAIL_CLOSED"}))
        return 2
    if args.verify_only:
        print(json.dumps(preflight, sort_keys=True))
        return 0
    command = build_claude_command(args.claude_executable, contract)
    if args.print_claude_command:
        print(json.dumps({"command": command}))
        return 0
    if args.output_root is None:
        print("--output-root is required", file=sys.stderr)
        return 2
    try:
        prompt = _prompt_text(contract, preflight)
        return _run_claude(command=command, prompt=prompt, output_root=args.output_root)
    except (ContractError, OSError, subprocess.TimeoutExpired) as exc:
        print(
            json.dumps(
                {"reason": str(exc), "status": "CLAUDE_SUPERVISOR_FAILED"},
                ensure_ascii=False,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
