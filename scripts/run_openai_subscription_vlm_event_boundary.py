"""ChatGPT 구독 Codex CLI로 동결 사건 경계 시험을 실행해."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import time
from typing import Iterable, Mapping

from scripts.local_vlm_event_boundary import (
    PROMPT,
    PROMPT_VERSION,
    RESULT_SCHEMA,
    BoundaryPrediction,
    parse_prediction,
    score_predictions,
)
from scripts.vlm_event_boundary_dense import (
    DENSE_PROMPT,
    DENSE_PROMPT_VERSION,
    DENSE_REPRESENTATION,
)


ALLOWED_MODELS = (
    "gpt-5.4-mini",
    "gpt-5.6-luna",
    "gpt-5.6-terra",
)
EXPECTED_MANIFEST_SHA256 = (
    "a0bd6ef5073508a14dd9be66cad9d65dea06d4ef4800a0a687af31c1b9163236"
)
EXPECTED_PAIR_COUNT = 74
MAX_PRIVATE_TEXT_BYTES = 4096


@dataclass(frozen=True, slots=True)
class InputContract:
    name: str
    representation: str
    prompt_version: str
    prompt: str
    image_suffixes: tuple[str, ...]


LEGACY_CONTRACT = InputContract(
    "legacy_4x2",
    "combined_4x2",
    PROMPT_VERSION,
    PROMPT,
    ("AB",),
)
DENSE_CONTRACT = InputContract(
    "boundary_dense_6x2",
    DENSE_REPRESENTATION,
    DENSE_PROMPT_VERSION,
    DENSE_PROMPT,
    ("A", "B"),
)
CONTRACTS = {contract.name: contract for contract in (LEGACY_CONTRACT, DENSE_CONTRACT)}


@dataclass(frozen=True, slots=True)
class FrozenInput:
    pair: str
    human: str
    image_paths: tuple[Path, ...]
    input_sha256: tuple[str, ...]

    @property
    def image_path(self) -> Path:
        if len(self.image_paths) != 1:
            raise ValueError("multiple_images")
        return self.image_paths[0]


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode()


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _write_new(path: Path, payload: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    path.chmod(0o600)


def _new_private_dir(path: Path) -> None:
    if path.exists():
        raise ValueError("output_exists")
    path.mkdir(mode=0o700)
    path.chmod(0o700)


def _require_private_source(path: Path, *, directory: bool = False) -> None:
    if path.is_symlink() or (not path.is_dir() if directory else not path.is_file()):
        raise ValueError("private_source_missing")
    expected = 0o700 if directory else 0o600
    if stat.S_IMODE(path.stat().st_mode) != expected:
        raise ValueError("private_source_mode")


def load_frozen_inputs(
    manifest_path: Path,
    input_dir: Path,
    *,
    expected_count: int = EXPECTED_PAIR_COUNT,
    contract: InputContract = LEGACY_CONTRACT,
) -> tuple[FrozenInput, ...]:
    manifest = json.loads(manifest_path.read_text())
    if (
        not isinstance(manifest, dict)
        or manifest.get("representation") != contract.representation
        or manifest.get("prompt_version") != contract.prompt_version
        or manifest.get("pair_count") != expected_count
        or not isinstance(manifest.get("inputs"), list)
        or len(manifest["inputs"]) != expected_count
    ):
        raise ValueError("manifest_contract")

    rows: list[FrozenInput] = []
    seen: set[str] = set()
    for raw in manifest["inputs"]:
        if not isinstance(raw, dict):
            raise ValueError("manifest_input")
        pair = raw.get("pair")
        human = raw.get("human")
        images = raw.get("images")
        if (
            not isinstance(pair, str)
            or not pair
            or pair in seen
            or human not in {"same_event", "different_event"}
            or not isinstance(images, list)
            or len(images) != len(contract.image_suffixes)
            or any(not isinstance(image, str) or len(image) != 64 for image in images)
        ):
            raise ValueError("manifest_input")
        seen.add(pair)
        image_paths = tuple(input_dir / f"{pair}-{suffix}.jpg" for suffix in contract.image_suffixes)
        actual_sha: list[str] = []
        for image_path, expected_sha in zip(image_paths, images, strict=True):
            if not image_path.is_file() or image_path.is_symlink():
                raise ValueError("input_missing")
            digest = _sha256(image_path.read_bytes())
            if digest != expected_sha:
                raise ValueError("input_hash_drift")
            actual_sha.append(digest)
        rows.append(FrozenInput(pair, human, image_paths, tuple(actual_sha)))
    return tuple(rows)


def build_codex_command(
    *,
    codex_path: Path,
    model: str,
    image_paths: Iterable[Path],
    schema_path: Path,
    output_path: Path,
    working_dir: Path,
    prompt: str,
) -> list[str]:
    if model not in ALLOWED_MODELS:
        raise ValueError("model_not_allowed")
    paths = tuple(image_paths)
    if not paths:
        raise ValueError("image_paths")
    return [
        str(codex_path),
        "exec",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--model",
        model,
        "--config",
        'model_reasoning_effort="low"',
        "--image",
        *(str(path) for path in paths),
        "--output-schema",
        str(schema_path),
        "--output-last-message",
        str(output_path),
        "--json",
        "--cd",
        str(working_dir),
        prompt,
    ]


def _percentiles(values: Iterable[float]) -> dict[str, float]:
    ordered = sorted(values)
    if not ordered:
        return {"p50": 0.0, "p95": 0.0, "max": 0.0}
    at = lambda fraction: ordered[round((len(ordered) - 1) * fraction)]
    return {"p50": at(0.5), "p95": at(0.95), "max": ordered[-1]}


def score_model_records(
    human: Mapping[str, str],
    records: Iterable[Mapping[str, object]],
    *,
    expected_count: int,
) -> dict[str, object]:
    predictions: dict[str, BoundaryPrediction | None] = {}
    latencies: list[float] = []
    for record in records:
        pair = record.get("pair")
        elapsed = record.get("elapsed_sec")
        if (
            not isinstance(pair, str)
            or pair in predictions
            or pair not in human
            or isinstance(elapsed, bool)
            or not isinstance(elapsed, (int, float))
            or elapsed < 0
        ):
            raise ValueError("record_contract")
        raw_prediction = record.get("prediction")
        predictions[pair] = (
            None
            if raw_prediction is None
            else parse_prediction(json.dumps(raw_prediction, separators=(",", ":")))
        )
        latencies.append(float(elapsed))
    if set(predictions) != set(human):
        raise ValueError("record_identity")
    score = score_predictions(human, predictions, expected_count=expected_count)  # type: ignore[arg-type]
    return {"score": asdict(score), "latency_sec": _percentiles(latencies)}


def _model_slugs(cache_path: Path) -> set[str]:
    payload = json.loads(cache_path.read_text())
    models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        raise ValueError("model_cache")
    return {
        str(model["slug"])
        for model in models
        if isinstance(model, dict) and isinstance(model.get("slug"), str)
    }


def _truncate_private(value: str) -> str:
    return value.encode()[:MAX_PRIVATE_TEXT_BYTES].decode(errors="replace")


def trace_is_tool_free(trace: str) -> bool:
    """Codex가 첨부 이미지 외 파일·도구를 보지 않았다는 event gate야."""
    saw_agent_message = False
    for line in trace.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return False
        if not isinstance(event, dict):
            return False
        if str(event.get("type", "")).startswith("item."):
            item = event.get("item")
            if not isinstance(item, dict) or item.get("type") not in {
                "agent_message",
                "reasoning",
            }:
                return False
            saw_agent_message = saw_agent_message or item.get("type") == "agent_message"
    return saw_agent_message


def classify_codex_failure(returncode: int, stdout: str, stderr: str) -> str:
    combined = f"{stdout}\n{stderr}".lower()
    if any(marker in combined for marker in (
        "429",
        "rate limit",
        "usage limit",
        "quota",
        "too many requests",
    )):
        return "quota_or_rate_limit"
    return f"codex_exit_{returncode}"


def operational_verdict(score: Mapping[str, object], errors: Iterable[object]) -> str:
    if "quota_or_rate_limit" in errors:
        return "INCONCLUSIVE_QUOTA"
    if score.get("overmerge") == 1 or (
        score.get("overmerge") == 0
        and score.get("same_correct") in {27, 28, 29, 30, 31}
    ):
        return "INCONCLUSIVE_NONDETERMINISTIC_BORDERLINE"
    verdict = score.get("verdict")
    return str(verdict) if isinstance(verdict, str) else "INVALID"


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in path.read_text().splitlines():
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError("ledger_row")
        rows.append(row)
    return rows


def run_experiment(args: argparse.Namespace) -> dict[str, object]:
    contract = CONTRACTS[args.input_contract]
    expected_manifest_sha256 = (
        EXPECTED_MANIFEST_SHA256
        if contract is LEGACY_CONTRACT
        else args.expected_manifest_sha256
    )
    if not isinstance(expected_manifest_sha256, str) or len(expected_manifest_sha256) != 64:
        raise ValueError("expected_manifest_sha256")
    source_root = args.source_root
    manifest_path = source_root / "frozen-manifest.json"
    input_dir = source_root / "inputs"
    _require_private_source(source_root, directory=True)
    _require_private_source(manifest_path)
    _require_private_source(input_dir, directory=True)
    if _sha256(manifest_path.read_bytes()) != expected_manifest_sha256:
        raise ValueError("source_manifest_drift")
    frozen_inputs = load_frozen_inputs(manifest_path, input_dir, contract=contract)

    if not args.codex_path.is_file() or not os.access(args.codex_path, os.X_OK):
        raise ValueError("codex_missing")
    version = subprocess.run(
        [str(args.codex_path), "--version"],
        check=True,
        text=True,
        capture_output=True,
        timeout=15,
    ).stdout.strip()
    login = subprocess.run(
        [str(args.codex_path), "login", "status"],
        check=True,
        text=True,
        capture_output=True,
        timeout=15,
    )
    login_text = f"{login.stdout}\n{login.stderr}"
    if "Logged in using ChatGPT" not in login_text:
        raise ValueError("chatgpt_login_required")
    missing_models = set(ALLOWED_MODELS) - _model_slugs(args.model_cache)
    if missing_models:
        raise ValueError("model_unavailable")

    _new_private_dir(args.output_dir)
    workspace = args.output_dir / "codex-workspace"
    workspace.mkdir(mode=0o700)
    workspace.chmod(0o700)
    blind_inputs = args.output_dir / "blind-inputs"
    blind_inputs.mkdir(mode=0o700)
    blind_inputs.chmod(0o700)
    blind_paths: dict[str, tuple[Path, ...]] = {}
    for row in frozen_inputs:
        pair_dir = blind_inputs / row.pair
        pair_dir.mkdir(mode=0o700)
        pair_dir.chmod(0o700)
        copied: list[Path] = []
        for ordinal, (source_path, expected_sha) in enumerate(
            zip(row.image_paths, row.input_sha256, strict=True),
            start=1,
        ):
            blind_path = pair_dir / f"input-{ordinal}.jpg"
            shutil.copyfile(source_path, blind_path)
            blind_path.chmod(0o600)
            if _sha256(blind_path.read_bytes()) != expected_sha:
                raise ValueError("blind_input_hash_drift")
            copied.append(blind_path)
        blind_paths[row.pair] = tuple(copied)
    schema_path = args.output_dir / "schema.json"
    _write_new(schema_path, _canonical_bytes(RESULT_SCHEMA))
    test_sheet_sha = _sha256(args.test_sheet.read_bytes())
    prompt_sha = _sha256(contract.prompt.encode())

    frozen_public = {
        "schema_version": "openai-subscription-vlm-event-boundary-v2",
        "source_manifest_sha256": expected_manifest_sha256,
        "source_pair_count": len(frozen_inputs),
        "source_input_sha256": [
            row.input_sha256[0] if len(row.input_sha256) == 1 else list(row.input_sha256)
            for row in frozen_inputs
        ],
        "representation": contract.representation,
        "prompt_version": contract.prompt_version,
        "prompt_sha256": prompt_sha,
        "test_sheet_sha256": test_sheet_sha,
        "codex_version": version,
        "auth_kind": "chatgpt_subscription",
        "models": list(ALLOWED_MODELS),
        "reasoning_effort": "low",
        "retry": 0,
        "model_identity_scope": "requested_slug_and_cache_only",
        "tool_or_file_access_allowed": False,
        "ledger_contains_human_gt_during_model_run": False,
    }
    _write_new(args.output_dir / "frozen-run.json", _canonical_bytes(frozen_public))

    summaries: dict[str, object] = {}
    human = {row.pair: row.human for row in frozen_inputs}
    for model in ALLOWED_MODELS:
        model_dir = args.output_dir / model
        raw_dir = model_dir / "raw"
        model_dir.mkdir(mode=0o700)
        raw_dir.mkdir(mode=0o700)
        model_dir.chmod(0o700)
        raw_dir.chmod(0o700)
        ledger_path = model_dir / "results.jsonl"
        descriptor = os.open(ledger_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        model_started = time.monotonic()
        with os.fdopen(descriptor, "wb") as ledger:
            for row in frozen_inputs:
                output_path = raw_dir / f"{row.pair}.json"
                command = build_codex_command(
                    codex_path=args.codex_path,
                    model=model,
                    image_paths=blind_paths[row.pair],
                    schema_path=schema_path,
                    output_path=output_path,
                    working_dir=blind_paths[row.pair][0].parent,
                    prompt=contract.prompt,
                )
                started = time.monotonic()
                prediction: BoundaryPrediction | None = None
                error: str | None = None
                raw = ""
                trace = ""
                try:
                    result = subprocess.run(
                        command,
                        text=True,
                        capture_output=True,
                        timeout=args.timeout_sec,
                        check=False,
                    )
                    trace = _truncate_private(result.stdout)
                    if result.returncode != 0:
                        error = classify_codex_failure(
                            result.returncode,
                            result.stdout,
                            result.stderr,
                        )
                    elif not trace_is_tool_free(result.stdout):
                        error = "tool_or_file_access_forbidden"
                    elif not output_path.is_file():
                        error = "output_missing"
                    else:
                        output_path.chmod(0o600)
                        raw = _truncate_private(output_path.read_text())
                        prediction = parse_prediction(raw)
                except subprocess.TimeoutExpired as exc:
                    error = "timeout"
                    trace = _truncate_private(str(exc.stdout or ""))
                except Exception as exc:  # measured call은 retry 없이 실패로 남겨.
                    error = type(exc).__name__
                elapsed = time.monotonic() - started
                record = {
                    "model": model,
                    "pair": row.pair,
                    "input_sha256": (
                        row.input_sha256[0]
                        if len(row.input_sha256) == 1
                        else list(row.input_sha256)
                    ),
                    "prompt_sha256": prompt_sha,
                    "elapsed_sec": elapsed,
                    "prediction": asdict(prediction) if prediction else None,
                    "error": error,
                    "raw": raw,
                    "trace": trace,
                }
                ledger.write(_canonical_bytes(record))
                ledger.flush()
                os.fsync(ledger.fileno())
                if error == "tool_or_file_access_forbidden":
                    raise ValueError("tool_or_file_access_forbidden")
        ledger_path.chmod(0o600)
        aggregate = score_model_records(
            human,
            _read_jsonl(ledger_path),
            expected_count=EXPECTED_PAIR_COUNT,
        )
        aggregate["wall_sec"] = time.monotonic() - model_started
        aggregate["ledger_sha256"] = _sha256(ledger_path.read_bytes())
        errors = [record.get("error") for record in _read_jsonl(ledger_path)]
        score = aggregate["score"]
        aggregate["operational_verdict"] = (
            operational_verdict(score, errors) if isinstance(score, dict) else "INVALID"
        )
        summaries[model] = aggregate

    summary = {
        "schema_version": "openai-subscription-vlm-event-boundary-summary-v2",
        "source_manifest_sha256": expected_manifest_sha256,
        "representation": contract.representation,
        "prompt_version": contract.prompt_version,
        "test_sheet_sha256": test_sheet_sha,
        "prompt_sha256": prompt_sha,
        "codex_version": version,
        "models": summaries,
    }
    summary["summary_sha256"] = _sha256(_canonical_bytes(summary))
    _write_new(args.output_dir / "summary.json", _canonical_bytes(summary))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--codex-path", type=Path, required=True)
    parser.add_argument("--model-cache", type=Path, required=True)
    parser.add_argument("--test-sheet", type=Path, required=True)
    parser.add_argument("--input-contract", choices=tuple(CONTRACTS), default=LEGACY_CONTRACT.name)
    parser.add_argument("--expected-manifest-sha256")
    parser.add_argument("--timeout-sec", type=int, default=240)
    return parser.parse_args()


def main() -> int:
    summary = run_experiment(parse_args())
    print(json.dumps({
        "status": "MEASURED_RUN_COMPLETE",
        "summary_sha256": summary["summary_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
