#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import plistlib
import re
import sqlite3
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Callable


class RebootVerificationError(RuntimeError):
    pass


_BOOT_SEC_PATTERN = re.compile(r"(?:^|[{\s,])sec\s*=\s*(\d+)\b")
_LABEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]+$")
_SECRET_PATTERN = re.compile(
    r"rtsp://|bearer\s|password|api[_-]?key|signed[_-]?url|"
    r"x-amz-signature|webhook",
    re.IGNORECASE,
)
_MEDIA_SUFFIXES = frozenset(
    {
        ".mp4",
        ".mov",
        ".mkv",
        ".avi",
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
        ".npy",
        ".npz",
        ".pt",
        ".pth",
        ".onnx",
    }
)
RunCommand = Callable[[Sequence[str]], str]


def parse_boot_sec(output: str) -> int:
    match = _BOOT_SEC_PATTERN.search(output)
    if match is None:
        raise RebootVerificationError("boot_sec_missing")
    return int(match.group(1))


def _services_by_label(
    services: Sequence[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    indexed: dict[str, Mapping[str, Any]] = {}
    for service in services:
        label = service.get("label")
        if (
            not isinstance(label, str)
            or not label
            or _LABEL_PATTERN.fullmatch(label) is None
        ):
            raise RebootVerificationError("service_label_invalid")
        if label in indexed:
            raise RebootVerificationError(f"service_label_duplicate:{label}")
        indexed[label] = service
    return indexed


def compare_immutable_services(
    expected_services: Sequence[Mapping[str, Any]],
    actual_services: Sequence[Mapping[str, Any]],
) -> None:
    expected = _services_by_label(expected_services)
    actual = _services_by_label(actual_services)
    if expected.keys() != actual.keys():
        raise RebootVerificationError("service_labels")

    for label, expected_service in expected.items():
        actual_service = actual[label]
        if expected_service.get("plist_sha256") != actual_service.get("plist_sha256"):
            raise RebootVerificationError(f"{label}:plist_sha256")

        expected_working_directory = expected_service.get("working_directory")
        if (
            expected_working_directory is not None
            and expected_working_directory
            != actual_service.get("working_directory")
        ):
            raise RebootVerificationError(f"{label}:working_directory")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_production_baseline(
    baseline_path: Path,
    launch_agents_dir: Path,
) -> int:
    try:
        payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RebootVerificationError("production_baseline_unreadable") from exc
    services = payload.get("services") if isinstance(payload, dict) else None
    if not isinstance(services, list):
        raise RebootVerificationError("production_baseline_services_invalid")

    expected = _services_by_label(services)
    actual: list[dict[str, Any]] = []
    for label in expected:
        plist_path = launch_agents_dir / f"{label}.plist"
        try:
            plist_hash = sha256_file(plist_path)
            with plist_path.open("rb") as file:
                plist = plistlib.load(file)
        except (OSError, plistlib.InvalidFileException) as exc:
            raise RebootVerificationError(f"{label}:plist_unreadable") from exc

        working_directory = plist.get("WorkingDirectory")
        if working_directory is not None and not isinstance(working_directory, str):
            raise RebootVerificationError(f"{label}:working_directory_invalid")
        actual.append(
            {
                "label": label,
                "plist_sha256": plist_hash,
                "working_directory": working_directory,
            }
        )

    compare_immutable_services(services, actual)
    return len(actual)


def _run_command(args: Sequence[str]) -> str:
    result = subprocess.run(
        tuple(args),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        command = Path(args[0]).name
        raise RebootVerificationError(
            f"command_failed:{command}:{result.returncode}"
        )
    return result.stdout


def _read_marker(marker_path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RebootVerificationError("marker_unreadable") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 2:
        raise RebootVerificationError("marker_schema")
    if payload.get("marker") != "R1_RUNTIME_P3_REBOOT_PENDING":
        raise RebootVerificationError("marker_name")
    return payload


def _required_string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise RebootVerificationError(f"marker_field:{key}")
    return value


def _verify_service_state(
    service_state: str,
    *,
    runtime_checkout: Path,
    runtime_root: Path,
    runtime_sha: str,
) -> None:
    required_fragments = (
        f"working directory = {runtime_checkout}",
        f"RESEARCH_RUNTIME_ROOT => {runtime_root}",
        f"RESEARCH_EXPECTED_HEAD => {runtime_sha}",
        "last exit code = 0",
    )
    for fragment in required_fragments:
        if fragment not in service_state:
            raise RebootVerificationError("target_service_state")


def _verify_local_ledger(runtime_root: Path) -> None:
    ledger_path = runtime_root / "ledger.sqlite3"
    uri = f"{ledger_path.resolve().as_uri()}?mode=ro&immutable=1"
    try:
        database = sqlite3.connect(uri, uri=True)
        provider_calls, cost_krw = database.execute(
            """
            select coalesce(sum(provider_calls), 0),
                   coalesce(sum(cost_krw), 0)
            from jobs
            """
        ).fetchone()
    except sqlite3.Error as exc:
        raise RebootVerificationError("ledger_unreadable") from exc
    finally:
        if "database" in locals():
            database.close()
    if provider_calls != 0 or cost_krw != 0:
        raise RebootVerificationError("provider_cost_nonzero")


def _verify_runtime_residue(runtime_root: Path) -> None:
    for path in runtime_root.rglob("*"):
        if path.is_file() and path.suffix.lower() in _MEDIA_SUFFIXES:
            raise RebootVerificationError("media_residue")

    for directory_name in ("events", "jobs", "logs"):
        directory = runtime_root / directory_name
        if not directory.exists():
            continue
        for path in directory.rglob("*"):
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                raise RebootVerificationError("runtime_artifact_unreadable") from exc
            if _SECRET_PATTERN.search(text):
                raise RebootVerificationError("secret_like_residue")


def verify_reboot_marker(
    marker_path: Path,
    *,
    run_command: RunCommand = _run_command,
) -> dict[str, int]:
    marker = _read_marker(marker_path)
    expected_host = _required_string(marker, "host")
    expected_user = _required_string(marker, "user")
    runtime_sha = _required_string(marker, "runtime_sha")
    runtime_checkout = Path(_required_string(marker, "runtime_checkout"))
    runtime_root = Path(_required_string(marker, "runtime_root"))
    legacy_root = Path(_required_string(marker, "legacy_root"))
    runtime_label = _required_string(marker, "runtime_label")
    target_plist = Path(_required_string(marker, "target_plist"))
    target_plist_sha = _required_string(marker, "target_plist_sha256")
    launch_agents_dir = Path(_required_string(marker, "launch_agents_dir"))
    baseline_path = Path(
        _required_string(marker, "production_baseline_artifact")
    )
    baseline_sha = _required_string(marker, "production_baseline_sha256")
    pre_reboot_boot_sec = marker.get("pre_reboot_boot_sec")
    if not isinstance(pre_reboot_boot_sec, int):
        raise RebootVerificationError("marker_field:pre_reboot_boot_sec")

    if run_command(("/bin/hostname",)).strip() != expected_host:
        raise RebootVerificationError("host")
    if run_command(("/usr/bin/id", "-un")).strip() != expected_user:
        raise RebootVerificationError("user")

    boot_sec = parse_boot_sec(
        run_command(("/usr/sbin/sysctl", "-n", "kern.boottime"))
    )
    if boot_sec == pre_reboot_boot_sec:
        raise RebootVerificationError("boot_id_unchanged")

    actual_runtime_sha = run_command(
        (
            "/usr/bin/git",
            "-C",
            str(runtime_checkout),
            "rev-parse",
            "HEAD",
        )
    ).strip()
    if actual_runtime_sha != runtime_sha:
        raise RebootVerificationError("runtime_sha")
    runtime_status = run_command(
        (
            "/usr/bin/git",
            "-C",
            str(runtime_checkout),
            "status",
            "--porcelain",
            "--untracked-files=all",
        )
    )
    if runtime_status:
        raise RebootVerificationError("runtime_checkout_dirty")

    if sha256_file(target_plist) != target_plist_sha:
        raise RebootVerificationError("target_plist_sha256")
    user_id = run_command(("/usr/bin/id", "-u")).strip()
    service_state = run_command(
        ("/bin/launchctl", "print", f"gui/{user_id}/{runtime_label}")
    )
    _verify_service_state(
        service_state,
        runtime_checkout=runtime_checkout,
        runtime_root=runtime_root,
        runtime_sha=runtime_sha,
    )

    if sha256_file(baseline_path) != baseline_sha:
        raise RebootVerificationError("production_baseline_sha256")
    production_services = verify_production_baseline(
        baseline_path,
        launch_agents_dir,
    )

    researchctl = runtime_checkout / "scripts/researchctl"
    status_output = run_command(
        (
            str(researchctl),
            "--root",
            str(runtime_root),
            "status",
            "--json",
        )
    )
    try:
        status = json.loads(status_output)
    except json.JSONDecodeError as exc:
        raise RebootVerificationError("runtime_status_invalid") from exc
    jobs = status.get("jobs") if isinstance(status, dict) else None
    if not isinstance(jobs, list):
        raise RebootVerificationError("runtime_status_jobs_invalid")
    if legacy_root.exists():
        raise RebootVerificationError("legacy_root_present")

    _verify_local_ledger(runtime_root)
    _verify_runtime_residue(runtime_root)
    return {
        "boot_sec": boot_sec,
        "jobs": len(jobs),
        "production_services": production_services,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--marker", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = verify_reboot_marker(args.marker)
    except RebootVerificationError as exc:
        print(f"R1_REBOOT_VERIFY_FAILED reason={exc}", file=sys.stderr)
        return 1

    print(f"R1_REBOOT_BOOT_ID_CHANGED new={result['boot_sec']}")
    print("R1_REBOOT_RUNTIME_HEAD_OK")
    print("R1_REBOOT_SERVICE_LOADED")
    print(
        "R1_REBOOT_PRODUCTION_IMMUTABLE_BASELINE_OK "
        f"services={result['production_services']}"
    )
    print(f"R1_REBOOT_RUNTIME_STATUS_OK jobs={result['jobs']}")
    print("R1_REBOOT_RESIDUE_ZERO")
    print("R1_RUNTIME_P3_REBOOT_RECOVERY_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
