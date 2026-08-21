"""Mac mini에서 Python→OpenAI VLM 3클립 one-shot smoke를 실행해."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
import sys
from typing import Callable, Mapping

from dotenv import dotenv_values

from scripts.rba_gme_activity import (
    GmeActivityError,
    parse_gme_activity,
)
from scripts.rba_openai_clip_aggregate import aggregate_clip_ledger
from scripts.rba_openai_frame_policy import materialize_frame_manifest
from scripts.rba_python_prescan import scan_video
from scripts.run_rba_openai_vlm import BudgetGuard, run_frame_manifest


RUNTIME_SCRIPT_FUNCTIONS: dict[str, Callable[..., object] | None] = {
    "scripts/rba_python_prescan.py": scan_video,
    "scripts/rba_gme_activity.py": parse_gme_activity,
    "scripts/rba_openai_frame_policy.py": materialize_frame_manifest,
    "scripts/rba_openai_clip_aggregate.py": aggregate_clip_ledger,
    "scripts/run_rba_openai_vlm.py": run_frame_manifest,
    "scripts/run_rba_openai_smoke.py": None,
}
RUNTIME_SCRIPT_PATHS = tuple(RUNTIME_SCRIPT_FUNCTIONS)


class SmokeContractError(ValueError):
    """3클립 기술 smoke 계약이 깨졌어."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode()


def _write_new(path: Path, value: object) -> None:
    if path.exists() or path.is_symlink():
        raise SmokeContractError("output_exists")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(_canonical_bytes(value))
        handle.flush()
        os.fsync(handle.fileno())
    path.chmod(0o600)


def _load_secret(secret_env: Path) -> str:
    if (
        not secret_env.is_file()
        or secret_env.is_symlink()
        or stat.S_IMODE(secret_env.stat().st_mode) != 0o600
    ):
        raise SmokeContractError("secret_file_contract")
    values = dotenv_values(secret_env)
    key = values.get("OPENAI_API_KEY")
    if set(values) != {"OPENAI_API_KEY"} or not isinstance(key, str) or len(key) < 20:
        raise SmokeContractError("secret_value_contract")
    return key


def _git_output(source_repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(source_repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise SmokeContractError("source_repo_contract")
    return completed.stdout.strip()


def _loaded_runtime_path(relative: str) -> Path:
    function = RUNTIME_SCRIPT_FUNCTIONS[relative]
    if function is None:
        raw_path = Path(__file__)
    else:
        module = sys.modules.get(function.__module__)
        module_file = getattr(module, "__file__", None)
        if not isinstance(module_file, str):
            raise SmokeContractError("runtime_source_contract")
        raw_path = Path(module_file)
    if not raw_path.is_file() or raw_path.is_symlink():
        raise SmokeContractError("runtime_source_contract")
    return raw_path.resolve()


def _source_provenance(source_repo: Path) -> dict[str, object]:
    if not source_repo.is_dir() or source_repo.is_symlink():
        raise SmokeContractError("source_repo_contract")
    resolved = source_repo.resolve()
    root = Path(_git_output(resolved, "rev-parse", "--show-toplevel")).resolve()
    if root != resolved:
        raise SmokeContractError("source_repo_contract")
    source_head = _git_output(resolved, "rev-parse", "--verify", "HEAD^{commit}")
    if not re.fullmatch(r"[0-9a-f]{40}", source_head):
        raise SmokeContractError("source_repo_contract")
    if _git_output(resolved, "status", "--porcelain", "--untracked-files=all"):
        raise SmokeContractError("source_repo_dirty")

    script_hashes: dict[str, str] = {}
    for relative in RUNTIME_SCRIPT_PATHS:
        _git_output(resolved, "ls-files", "--error-unmatch", "--", relative)
        script = resolved / relative
        if not script.is_file() or script.is_symlink():
            raise SmokeContractError("runtime_script_contract")
        script_hash = _sha256(script)
        if _sha256(_loaded_runtime_path(relative)) != script_hash:
            raise SmokeContractError("runtime_source_mismatch")
        script_hashes[relative] = script_hash
    return {
        "source_head": source_head,
        "runtime_script_sha256": script_hashes,
    }


def run_smoke(
    *,
    smoke_manifest: Path,
    runtime_root: Path,
    secret_env: Path,
    client_factory: Callable[[str], object],
    max_run_usd: float = 5.0,
    request_ceiling_usd: float = 0.25,
    execution_hostname: str,
    source_repo: Path,
) -> dict[str, object]:
    if not execution_hostname:
        raise SmokeContractError("execution_provenance_contract")
    provenance = _source_provenance(source_repo)
    raw = json.loads(smoke_manifest.read_text())
    clips = raw.get("clips") if isinstance(raw, dict) else None
    if (
        not isinstance(raw, dict)
        or raw.get("schema_version") != "rba-openai-smoke-manifest-v1"
        or raw.get("clip_count") != 3
        or not isinstance(clips, list)
        or len(clips) != 3
    ):
        raise SmokeContractError("smoke_manifest_contract")
    if runtime_root.exists() or runtime_root.is_symlink():
        raise SmokeContractError("runtime_exists")
    runtime_root.mkdir(parents=True, mode=0o700)
    runtime_root.chmod(0o700)
    key = _load_secret(secret_env)
    client = client_factory(key)
    budget = BudgetGuard(
        max_run_usd=max_run_usd,
        request_ceiling_usd=request_ceiling_usd,
    )
    ledger = runtime_root / "window-results.jsonl"
    clip_reports: list[dict[str, object]] = []
    request_count = 0

    for raw_clip in clips:
        if not isinstance(raw_clip, dict):
            raise SmokeContractError("smoke_clip_contract")
        clip_ref = raw_clip.get("clip_ref")
        media_path = raw_clip.get("media_path")
        media_sha = raw_clip.get("media_sha256")
        gme_run = raw_clip.get("gme_run")
        if (
            not isinstance(clip_ref, str)
            or not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", clip_ref)
            or not isinstance(media_path, str)
            or not isinstance(media_sha, str)
            or len(media_sha) != 64
            or not isinstance(gme_run, Mapping)
        ):
            if not isinstance(gme_run, Mapping):
                raise SmokeContractError("gme_run_contract")
            raise SmokeContractError("smoke_clip_contract")
        video = Path(media_path)
        if not video.is_file() or video.is_symlink() or _sha256(video) != media_sha:
            raise SmokeContractError("smoke_media_drift")
        clip_root = runtime_root / clip_ref
        clip_root.mkdir(mode=0o700)
        prescan = scan_video(
            video,
            summary_output=clip_root / "prescan-summary.json",
            sidecar_output=clip_root / "prescan-frames.jsonl.gz",
            max_analysis_fps=30.0,
        )
        try:
            gme_context = parse_gme_activity(
                gme_run,
                duration_sec=float(prescan["decode"]["duration_sec"]),  # type: ignore[index]
            )
        except GmeActivityError as exc:
            raise SmokeContractError("gme_run_contract") from exc
        frame_manifest = materialize_frame_manifest(
            video,
            output_dir=clip_root / "arm-a-frames",
            base_fps=4.0,
            dense_fps=20.0,
            dense_intervals=[],
            gme_context=gme_context,
            window_sec=6.0,
            overlap_sec=1.0,
        )
        run_summary = run_frame_manifest(
            client=client,
            clip_ref=clip_ref,
            manifest_path=clip_root / "arm-a-frames" / "frame-manifest.json",
            ledger_path=ledger,
            budget_guard=budget,
        )
        expected_windows = [
            str(window["window_id"]) for window in frame_manifest["windows"]
        ]
        aggregate = aggregate_clip_ledger(
            ledger,
            clip_ref=clip_ref,
            expected_window_ids=expected_windows,
            output=clip_root / "aggregate.json",
        )
        request_count += int(run_summary["api_request_count"])
        clip_reports.append(
            {
                "clip_ref": clip_ref,
                "status": aggregate["status"],
                "decoded_frames": prescan["decode"]["decoded_frames"],  # type: ignore[index]
                "analyzed_frames": prescan["decode"]["analyzed_frames"],  # type: ignore[index]
                "vlm_frame_count": frame_manifest["actual_frame_count"],
                "window_count": run_summary["window_count"],
                "complete_window_count": run_summary["complete_window_count"],
                "failed_window_count": run_summary["failed_window_count"],
                "estimated_cost_usd": run_summary["estimated_cost_usd"],
            }
        )
    report: dict[str, object] = {
        "schema_version": "rba-openai-smoke-report-v1",
        "status": "complete"
        if all(clip["status"] == "complete" for clip in clip_reports)
        else "incomplete",
        "clip_count": len(clip_reports),
        "complete_clips": sum(
            clip["status"] == "complete" for clip in clip_reports
        ),
        "request_count": request_count,
        "estimated_cost_usd": round(budget.spent_usd, 8),
        "max_run_usd": max_run_usd,
        "request_ceiling_usd": request_ceiling_usd,
        "execution_hostname": execution_hostname,
        **provenance,
        "clips": clip_reports,
    }
    _write_new(runtime_root / "smoke-report.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke-manifest", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--secret-env", type=Path, required=True)
    parser.add_argument("--max-run-usd", type=float, default=5.0)
    parser.add_argument("--request-ceiling-usd", type=float, default=0.25)
    parser.add_argument("--source-repo", type=Path, required=True)
    args = parser.parse_args()
    from openai import OpenAI

    report = run_smoke(
        smoke_manifest=args.smoke_manifest,
        runtime_root=args.runtime_root,
        secret_env=args.secret_env,
        client_factory=lambda key: OpenAI(api_key=key, timeout=120.0, max_retries=2),
        max_run_usd=args.max_run_usd,
        request_ceiling_usd=args.request_ceiling_usd,
        execution_hostname=socket.gethostname(),
        source_repo=args.source_repo,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "clip_count": report["clip_count"],
                "request_count": report["request_count"],
                "estimated_cost_usd": report["estimated_cost_usd"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if report["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
