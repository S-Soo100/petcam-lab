"""Build and freeze a reproducible private runtime for v2.5 shadow inference."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import stat
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

try:
    from scripts.build_yolo26n_v25_owner_hardcase_queue import (
        RUNTIME_FINGERPRINT_KEYS,
        _atomic_exchange_paths,
        _atomic_rename_no_overwrite,
        _hash_regular_file,
        _read_regular_file_bytes,
        _read_private_snapshot,
        _private_staging,
        _publish_verified_directory_new,
        _write_staging_bytes_new,
        directory_contract_sha256,
        directory_identity_snapshot,
        current_runtime_fingerprint,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from build_yolo26n_v25_owner_hardcase_queue import (  # type: ignore[no-redef]
        RUNTIME_FINGERPRINT_KEYS,
        _atomic_exchange_paths,
        _atomic_rename_no_overwrite,
        _hash_regular_file,
        _read_regular_file_bytes,
        _read_private_snapshot,
        _private_staging,
        _publish_verified_directory_new,
        _write_staging_bytes_new,
        directory_contract_sha256,
        directory_identity_snapshot,
        current_runtime_fingerprint,
    )


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_APPROVED_DISTRIBUTIONS = {
    "numpy": "2.4.4",
    "opencv-python": "5.0.0.93",
    "pillow": "12.2.0",
    "torch": "2.12.0",
    "torchvision": "0.27.0",
    "ultralytics": "8.4.104",
}
_APPROVED_RUNTIME_VERSIONS = {
    "numpy_version": "2.4.4",
    "opencv_version": "5.0.0",
    "pillow_version": "12.2.0",
    "torch_version": "2.12.0",
    "torchvision_version": "0.27.0",
    "ultralytics_version": "8.4.104",
}
_WRITE_COUNTS = {
    "db_write_count": 0,
    "r2_write_count": 0,
    "service_write_count": 0,
    "production_model_write_count": 0,
    "gme_write_count": 0,
    "labeling_web_write_count": 0,
}
_INFERENCE_CODE_BUNDLE = (
    "scripts/build_yolo26n_v25_owner_hardcase_queue.py",
    "scripts/build_yolo26n_v24b_future_holdout.py",
    "scripts/run_yolo26n_v24b_postprocess.py",
    "scripts/select_yolo26n_v24b_postprocess.py",
    "scripts/evaluate_yolo26n_v24b_future_holdout.py",
    "scripts/validate_yolo26n_v24b_future_holdout_export.py",
)


def _is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def isolated_sync_invocation(
    *,
    execution_repo: Path,
    runtime_root: Path,
    uv_binary: Path,
    python_binary: Path,
    protected_roots: Sequence[Path] = (),
) -> tuple[tuple[str, ...], dict[str, str]]:
    roots = tuple(protected_roots)
    try:
        real_parent = runtime_root.parent.resolve(strict=True)
        resolved_target = real_parent / runtime_root.name
        resolved_roots = tuple(root.resolve(strict=True) for root in roots)
        real_execution_repo = execution_repo.resolve(strict=True)
    except (FileNotFoundError, OSError):
        raise ValueError("isolated runtime target contract mismatch") from None
    if (
        any(
            not path.is_absolute()
            for path in (execution_repo, runtime_root, uv_binary, python_binary)
        )
        or not execution_repo.is_dir()
        or execution_repo.is_symlink()
        or real_execution_repo != execution_repo
        or uv_binary.is_symlink()
        or not uv_binary.is_file()
        or python_binary.is_symlink()
        or not python_binary.is_file()
        or not runtime_root.parent.is_dir()
        or runtime_root.parent.is_symlink()
        or real_parent != runtime_root.parent
        or stat.S_IMODE(runtime_root.parent.lstat().st_mode) != 0o700
        or runtime_root.exists()
        or runtime_root.is_symlink()
        or _is_within(resolved_target, real_execution_repo)
        or any(_is_within(resolved_target, root) for root in resolved_roots)
    ):
        raise ValueError("isolated runtime target contract mismatch")
    return (
        (
            str(uv_binary),
            "sync",
            "--frozen",
            "--only-group",
            "train",
            "--no-install-project",
            "--python",
            str(python_binary),
            "--project",
            str(execution_repo),
        ),
        {
            "UV_PROJECT_ENVIRONMENT": str(runtime_root),
            "UV_NO_PROGRESS": "1",
            "UV_PYTHON_DOWNLOADS": "never",
        },
    )


def _write_private_bytes_new(path: Path, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)


def _protected_inventory_sha256(roots: Sequence[Path]) -> str:
    digest = hashlib.sha256()
    for root in sorted((path.resolve(strict=True) for path in roots), key=str):
        metadata = root.lstat()
        if root.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
            raise ValueError("protected shared runtime inventory mismatch")
        digest.update(str(root).encode())
        for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
            child = path.lstat()
            relative = path.relative_to(root).as_posix().encode()
            digest.update(len(relative).to_bytes(4, "big"))
            digest.update(relative)
            digest.update(child.st_mode.to_bytes(8, "big"))
            digest.update(child.st_size.to_bytes(8, "big"))
            digest.update(child.st_mtime_ns.to_bytes(8, "big"))
            digest.update(child.st_ctime_ns.to_bytes(8, "big"))
            if stat.S_ISLNK(child.st_mode):
                target = os.readlink(path).encode()
                digest.update(len(target).to_bytes(4, "big"))
                digest.update(target)
            elif not (stat.S_ISDIR(child.st_mode) or stat.S_ISREG(child.st_mode)):
                raise ValueError("protected shared runtime inventory mismatch")
    return digest.hexdigest()


def reserve_isolated_runtime_build(
    *,
    execution_repo: Path,
    runtime_root: Path,
    uv_binary: Path,
    python_binary: Path,
    protected_roots: Sequence[Path] = (),
) -> tuple[tuple[str, ...], dict[str, str], tuple[object, ...]]:
    if (
        len(protected_roots) != 25
        or len({root.resolve(strict=True) for root in protected_roots}) != 25
        or any(root.is_symlink() or root.resolve(strict=True) != root for root in protected_roots)
    ):
        raise ValueError("protected shared runtime inventory mismatch")
    protected_inventory_sha256 = _protected_inventory_sha256(protected_roots)
    command, environment = isolated_sync_invocation(
        execution_repo=execution_repo,
        runtime_root=runtime_root,
        uv_binary=uv_binary,
        python_binary=python_binary,
        protected_roots=protected_roots,
    )
    lock_payload = _json_bytes(
        {
            "schema": "yolo26n-v25-isolated-runtime-started-v1",
            "status": "STARTED",
            "runtime_root": str(runtime_root),
            "uv_lock_sha256": _hash_regular_file(execution_repo / "uv.lock"),
            "uv_binary_sha256": _hash_regular_file(uv_binary),
            "python_binary_sha256": _hash_regular_file(python_binary),
            "protected_root_count": 25,
            "protected_inventory_sha256": protected_inventory_sha256,
            **_WRITE_COUNTS,
        }
    )
    _write_private_bytes_new(
        runtime_root.parent / "runtime-build.started.private.json", lock_payload
    )
    _write_private_bytes_new(
        runtime_root.parent / "uv.lock",
        _read_regular_file_bytes(execution_repo / "uv.lock"),
    )
    runtime_root.mkdir(mode=0o700)
    os.chmod(runtime_root, 0o700)
    return command, environment, directory_identity_snapshot(runtime_root)


def build_isolated_runtime(
    *,
    execution_repo: Path,
    runtime_root: Path,
    uv_binary: Path,
    python_binary: Path,
    protected_roots: Sequence[Path] = (),
    runner=subprocess.run,
) -> dict[str, str]:
    command, environment, identity = reserve_isolated_runtime_build(
        execution_repo=execution_repo,
        runtime_root=runtime_root,
        uv_binary=uv_binary,
        python_binary=python_binary,
        protected_roots=protected_roots,
    )
    started = _read_private_snapshot(
        runtime_root.parent / "runtime-build.started.private.json"
    )
    copied_lock = _read_private_snapshot(runtime_root.parent / "uv.lock")
    started_payload = json.loads(started.payload)
    runner(
        command,
        cwd=execution_repo,
        env={**os.environ, **environment},
        check=True,
        capture_output=True,
        text=True,
    )
    current = runtime_root.lstat()
    if (
        current.st_dev,
        current.st_ino,
        current.st_mode,
    ) != identity[:3] or _read_private_snapshot(
        runtime_root.parent / "runtime-build.started.private.json"
    ) != started or _read_private_snapshot(runtime_root.parent / "uv.lock") != copied_lock or _protected_inventory_sha256(
        protected_roots
    ) != started_payload.get("protected_inventory_sha256"):
        raise ValueError("isolated runtime root changed during sync")
    return {"status": "V25_ISOLATED_RUNTIME_SYNCED"}


def _canonical_distributions(
    distributions: Sequence[tuple[str, str]],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    names: set[str] = set()
    for raw_name, raw_version in distributions:
        name = str(raw_name).lower()
        version = str(raw_version)
        if not name or not version or name in names or "\n" in name or "\n" in version:
            raise ValueError("isolated runtime distribution contract mismatch")
        names.add(name)
        rows.append({"name": name, "version": version})
    rows.sort(key=lambda row: (row["name"], row["version"]))
    return rows


def _distribution_sha256(rows: Sequence[Mapping[str, str]]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        digest.update(f"{row['name']}=={row['version']}\n".encode())
    return digest.hexdigest()


def current_distribution_rows() -> list[tuple[str, str]]:
    rows = [
        (
            str(distribution.metadata.get("Name", "")).lower(),
            str(distribution.version),
        )
        for distribution in importlib.metadata.distributions()
    ]
    canonical = _canonical_distributions(rows)
    return [(row["name"], row["version"]) for row in canonical]


def build_contract_documents(
    *,
    implementation_commit: str,
    pyproject_sha256: str,
    uv_lock_sha256: str,
    builder_code_sha256: str,
    inference_code_sha256: str,
    checkpoint_sha256: str,
    dataset_manifest_sha256: str,
    python_version: str,
    runtime_fingerprint: Mapping[str, str],
    distributions: Sequence[tuple[str, str]],
) -> tuple[dict[str, object], dict[str, object]]:
    pins = {
        "pyproject_sha256": pyproject_sha256,
        "uv_lock_sha256": uv_lock_sha256,
        "builder_code_sha256": builder_code_sha256,
        "inference_code_sha256": inference_code_sha256,
        "checkpoint_sha256": checkpoint_sha256,
        "dataset_manifest_sha256": dataset_manifest_sha256,
    }
    rows = _canonical_distributions(distributions)
    versions = {row["name"]: row["version"] for row in rows}
    opencv_wheels = {
        name
        for name in versions
        if name
        in {
            "opencv-python",
            "opencv-python-headless",
            "opencv-contrib-python",
            "opencv-contrib-python-headless",
        }
    }
    runtime = dict(runtime_fingerprint)
    if (
        _COMMIT.fullmatch(implementation_commit) is None
        or any(_SHA256.fullmatch(value) is None for value in pins.values())
        or re.fullmatch(r"3\.12\.\d+", python_version) is None
        or set(runtime) != RUNTIME_FINGERPRINT_KEYS
        or any(not isinstance(value, str) or not value for value in runtime.values())
        or runtime.get("uv_lock_sha256") != uv_lock_sha256
        or runtime.get("distributions_sha256") != _distribution_sha256(rows)
        or any(versions.get(name) != version for name, version in _APPROVED_DISTRIBUTIONS.items())
        or opencv_wheels != {"opencv-python"}
        or any(runtime.get(name) != version for name, version in _APPROVED_RUNTIME_VERSIONS.items())
    ):
        raise ValueError("isolated runtime build contract mismatch")
    sync_contract = {
        "dependency_group": "train",
        "frozen": True,
        "only_group": True,
        "no_install_project": True,
        "python": "3.12",
    }
    build = {
        "schema": "yolo26n-v25-isolated-runtime-build-v1",
        "status": "V25_ISOLATED_RUNTIME_READY",
        "implementation_commit": implementation_commit,
        "python_version": python_version,
        **pins,
        "sync_contract": sync_contract,
        "distribution_count": len(rows),
        "distributions": rows,
        "runtime": runtime,
        **_WRITE_COUNTS,
    }
    preflight = {
        "schema": "yolo26n-v24b-runtime-preflight-v1",
        "status": "PREFLIGHT_OK",
        "implementation_commit": implementation_commit,
        "code_bundle_sha256": inference_code_sha256,
        "checkpoint_sha256": checkpoint_sha256,
        "dataset_manifest_sha256": dataset_manifest_sha256,
        "runtime": runtime,
        "prohibited_inputs": ["internal-test151", "owner-external60"],
        "writes": ["private-local-artifacts-only"],
    }
    return build, preflight


def validate_contract_documents(
    *,
    build: Mapping[str, object],
    preflight: Mapping[str, object],
    current_runtime_fingerprint: Mapping[str, str],
    current_distributions: Sequence[tuple[str, str]],
) -> None:
    rows = _canonical_distributions(current_distributions)
    stored_rows = build.get("distributions")
    current_runtime = dict(current_runtime_fingerprint)
    if (
        build.get("schema") != "yolo26n-v25-isolated-runtime-build-v1"
        or build.get("status") != "V25_ISOLATED_RUNTIME_READY"
        or stored_rows != rows
        or build.get("distribution_count") != len(rows)
        or build.get("runtime") != current_runtime
        or current_runtime.get("distributions_sha256") != _distribution_sha256(rows)
        or preflight.get("schema") != "yolo26n-v24b-runtime-preflight-v1"
        or preflight.get("status") != "PREFLIGHT_OK"
        or preflight.get("runtime") != current_runtime
        or preflight.get("implementation_commit") != build.get("implementation_commit")
        or preflight.get("checkpoint_sha256") != build.get("checkpoint_sha256")
        or preflight.get("dataset_manifest_sha256")
        != build.get("dataset_manifest_sha256")
    ):
        raise ValueError("isolated runtime drift")


def _git_state(execution_repo: Path) -> tuple[str, bool]:
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=execution_repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    status = subprocess.run(
        [
            "git",
            "status",
            "--porcelain",
            "--untracked-files=all",
            "--ignored=matching",
        ],
        cwd=execution_repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return head, status == ""


def _scripts_tree_manifest(execution_repo: Path) -> dict[str, str]:
    scripts_root = execution_repo / "scripts"
    root_metadata = scripts_root.lstat()
    if scripts_root.is_symlink() or not stat.S_ISDIR(root_metadata.st_mode):
        raise ValueError("isolated runtime scripts tree mismatch")
    manifest: dict[str, str] = {}
    pending = [scripts_root]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                path = Path(entry.path)
                metadata = path.lstat()
                if stat.S_ISLNK(metadata.st_mode):
                    raise ValueError("isolated runtime scripts tree mismatch")
                if stat.S_ISDIR(metadata.st_mode):
                    pending.append(path)
                    continue
                if not stat.S_ISREG(metadata.st_mode):
                    raise ValueError("isolated runtime scripts tree mismatch")
                relative = path.relative_to(execution_repo).as_posix()
                manifest[relative] = _hash_regular_file(path)
    return dict(sorted(manifest.items()))


def _approved_scripts_manifest(execution_repo: Path) -> dict[str, str]:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--", "scripts"],
        cwd=execution_repo,
        check=True,
        capture_output=True,
    )
    try:
        tracked = {
            raw.decode("utf-8")
            for raw in result.stdout.split(b"\0")
            if raw
        }
    except UnicodeDecodeError:
        raise ValueError("isolated runtime tracked scripts mismatch") from None
    actual = _scripts_tree_manifest(execution_repo)
    if not tracked or set(actual) != tracked:
        raise ValueError("isolated runtime tracked scripts mismatch")
    return actual


def _assert_runtime_synchronized(
    *, execution_repo: Path, runtime_root: Path, uv_binary: Path
) -> str:
    if (
        not uv_binary.is_absolute()
        or uv_binary.is_symlink()
        or not uv_binary.is_file()
        or not runtime_root.is_dir()
        or runtime_root.is_symlink()
    ):
        raise ValueError("isolated runtime sync-check path mismatch")
    command = [
        str(uv_binary),
        "sync",
        "--frozen",
        "--only-group",
        "train",
        "--no-install-project",
        "--python",
        str(runtime_root / "bin/python"),
        "--project",
        str(execution_repo),
        "--check",
    ]
    environment = {
        **os.environ,
        "UV_PROJECT_ENVIRONMENT": str(runtime_root),
        "UV_NO_PROGRESS": "1",
        "UV_PYTHON_DOWNLOADS": "never",
    }
    subprocess.run(
        command,
        cwd=execution_repo,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    return _hash_regular_file(uv_binary)


def finalize_runtime_contract(
    *,
    execution_repo: Path,
    runtime_root: Path,
    uv_binary: Path,
    implementation_commit: str,
    checkpoint: Path,
    expected_checkpoint_sha256: str,
    dataset_manifest: Path,
    expected_dataset_manifest_sha256: str,
    output_dir: Path,
) -> dict[str, object]:
    paths = {
        "pyproject": execution_repo / "pyproject.toml",
        "uv_lock": execution_repo / "uv.lock",
        "builder": execution_repo
        / "scripts/build_yolo26n_v25_isolated_runtime.py",
        "inference": execution_repo
        / "scripts/build_yolo26n_v25_owner_hardcase_queue.py",
        "launcher": execution_repo
        / "scripts/launch_yolo26n_v25_isolated_runtime.py",
        "checkpoint": checkpoint,
        "dataset": dataset_manifest,
        "started": runtime_root.parent / "runtime-build.started.private.json",
        "runtime_lock": runtime_root.parent / "uv.lock",
    }
    for relative in _INFERENCE_CODE_BUNDLE:
        paths[f"code:{relative}"] = execution_repo / relative
    if (
        any(
            not path.is_absolute()
            for path in (
                execution_repo,
                runtime_root,
                uv_binary,
                checkpoint,
                dataset_manifest,
                output_dir,
            )
        )
        or execution_repo.is_symlink()
        or execution_repo.resolve(strict=True) != execution_repo
        or runtime_root.is_symlink()
        or not runtime_root.is_dir()
        or runtime_root.resolve(strict=True) != runtime_root
        or stat.S_IMODE(runtime_root.lstat().st_mode) != 0o700
        or not Path(sys.prefix).samefile(runtime_root)
        or output_dir.parent != runtime_root.parent
        or runtime_root.parent.is_symlink()
        or runtime_root.parent.resolve(strict=True) != runtime_root.parent
        or stat.S_IMODE(runtime_root.parent.lstat().st_mode) != 0o700
    ):
        raise ValueError("isolated runtime finalization path mismatch")
    head, clean = _git_state(execution_repo)
    if head != implementation_commit or not clean:
        raise ValueError("isolated runtime implementation checkout mismatch")
    approved_scripts = _approved_scripts_manifest(execution_repo)
    uv_binary_sha256 = _assert_runtime_synchronized(
        execution_repo=execution_repo,
        runtime_root=runtime_root,
        uv_binary=uv_binary,
    )

    before = {name: _hash_regular_file(path) for name, path in paths.items()}
    if (
        before["checkpoint"] != expected_checkpoint_sha256
        or before["dataset"] != expected_dataset_manifest_sha256
    ):
        raise ValueError("isolated runtime input SHA mismatch")
    rows = current_distribution_rows()
    fingerprint = current_runtime_fingerprint()
    try:
        started = json.loads(
            _read_private_snapshot(paths["started"]).payload.decode("utf-8")
        )
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("isolated runtime STARTED contract mismatch") from None
    started_keys = {
        "schema",
        "status",
        "runtime_root",
        "uv_lock_sha256",
        "uv_binary_sha256",
        "python_binary_sha256",
        "protected_root_count",
        "protected_inventory_sha256",
        *_WRITE_COUNTS,
    }
    if (
        not isinstance(started, dict)
        or set(started) != started_keys
        or started.get("schema") != "yolo26n-v25-isolated-runtime-started-v1"
        or started.get("status") != "STARTED"
        or started.get("runtime_root") != str(runtime_root)
        or started.get("uv_lock_sha256") != before["uv_lock"]
        or before["runtime_lock"] != before["uv_lock"]
        or started.get("uv_binary_sha256") != uv_binary_sha256
        or started.get("python_binary_sha256")
        != fingerprint.get("python_binary_sha256")
        or started.get("protected_root_count") != 25
        or _SHA256.fullmatch(str(started.get("protected_inventory_sha256"))) is None
        or any(started.get(key) != 0 for key in _WRITE_COUNTS)
    ):
        raise ValueError("isolated runtime STARTED contract mismatch")
    if fingerprint.get("uv_lock_sha256") != before["uv_lock"]:
        raise ValueError("isolated runtime lock mismatch")
    build, preflight = build_contract_documents(
        implementation_commit=implementation_commit,
        pyproject_sha256=before["pyproject"],
        uv_lock_sha256=before["uv_lock"],
        builder_code_sha256=before["builder"],
        inference_code_sha256=before["inference"],
        checkpoint_sha256=before["checkpoint"],
        dataset_manifest_sha256=before["dataset"],
        python_version=".".join(str(value) for value in sys.version_info[:3]),
        runtime_fingerprint=fingerprint,
        distributions=rows,
    )
    build["uv_binary_sha256"] = uv_binary_sha256
    build["launcher_code_sha256"] = before["launcher"]
    build["sync_check_status"] = "UV_SYNC_CHECK_OK"
    code_bundle = {
        relative: before[f"code:{relative}"] for relative in _INFERENCE_CODE_BUNDLE
    }
    build["inference_code_bundle"] = code_bundle
    build["inference_code_bundle_sha256"] = hashlib.sha256(
        json.dumps(code_bundle, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    build["inference_scripts_manifest"] = approved_scripts
    build["inference_scripts_manifest_sha256"] = hashlib.sha256(
        json.dumps(approved_scripts, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    after = {name: _hash_regular_file(path) for name, path in paths.items()}
    current_rows = current_distribution_rows()
    current_fingerprint = current_runtime_fingerprint()
    if (
        before != after
        or rows != current_rows
        or fingerprint != current_fingerprint
        or approved_scripts != _approved_scripts_manifest(execution_repo)
    ):
        raise ValueError("isolated runtime changed during finalization")
    validate_contract_documents(
        build=build,
        preflight=preflight,
        current_runtime_fingerprint=current_fingerprint,
        current_distributions=current_rows,
    )
    contract_sha = publish_contract_directory(
        build=build, preflight=preflight, output_dir=output_dir
    )
    preflight_sha = _hash_regular_file(
        output_dir / "runtime-preflight.private.json"
    )
    build_sha = _hash_regular_file(output_dir / "runtime-build.private.json")
    return {
        "status": "V25_ISOLATED_RUNTIME_READY",
        "distribution_count": len(rows),
        "contract_sha256": contract_sha,
        "runtime_preflight_sha256": preflight_sha,
        "runtime_build_sha256": build_sha,
    }


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode()


def _quarantine_owned_runtime_contract(
    public: Path, expected_identity: tuple[object, ...]
) -> bool:
    """Relocate only the directory root inode created by this publisher."""
    quarantine = _private_staging(public.parent, f"{public.name}-failed")
    sentinel = quarantine / "sentinel"
    sentinel.mkdir(mode=0o700)
    sentinel_identity = directory_identity_snapshot(sentinel)
    try:
        _atomic_exchange_paths(public, sentinel)
    except (FileNotFoundError, OSError):
        return False
    captured = sentinel.lstat()
    captured_root = (captured.st_dev, captured.st_ino, captured.st_mode)
    if captured_root != expected_identity[:3]:
        try:
            _atomic_exchange_paths(public, sentinel)
        except BaseException as error:
            raise RuntimeError("runtime contract rival rollback failed") from error
        return False
    captured_sentinel = quarantine / "public-sentinel"
    _atomic_rename_no_overwrite(public, captured_sentinel)
    if directory_identity_snapshot(captured_sentinel) != sentinel_identity:
        raise RuntimeError("runtime contract sentinel ownership mismatch")
    return True


def publish_contract_directory(
    *,
    build: Mapping[str, object],
    preflight: Mapping[str, object],
    output_dir: Path,
) -> str:
    try:
        real_parent = output_dir.parent.resolve(strict=True)
    except (FileNotFoundError, OSError):
        raise ValueError("isolated runtime publication path mismatch") from None
    if (
        not output_dir.is_absolute()
        or output_dir.parent.is_symlink()
        or not output_dir.parent.is_dir()
        or real_parent != output_dir.parent
        or stat.S_IMODE(output_dir.parent.lstat().st_mode) != 0o700
        or output_dir.exists()
        or output_dir.is_symlink()
    ):
        if output_dir.exists():
            raise FileExistsError(output_dir)
        raise ValueError("isolated runtime publication path mismatch")
    staging = _private_staging(output_dir.parent, output_dir.name)
    _write_staging_bytes_new(
        staging / "runtime-build.private.json", _json_bytes(dict(build))
    )
    _write_staging_bytes_new(
        staging / "runtime-preflight.private.json", _json_bytes(dict(preflight))
    )
    expected_identity = directory_identity_snapshot(staging)
    expected_sha = directory_contract_sha256(staging)
    _publish_verified_directory_new(staging, output_dir, expected_identity)
    try:
        if (
            directory_identity_snapshot(output_dir) != expected_identity
            or directory_contract_sha256(output_dir) != expected_sha
        ):
            raise ValueError("isolated runtime publication drift")
    except BaseException:
        _quarantine_owned_runtime_contract(output_dir, expected_identity)
        raise
    return expected_sha


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Finalize a private YOLO v2.5 isolated runtime contract."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--execution-repo", type=Path, required=True)
    build.add_argument("--runtime-root", type=Path, required=True)
    build.add_argument("--uv-binary", type=Path, required=True)
    build.add_argument("--python-binary", type=Path, required=True)
    build.add_argument(
        "--protected-root", type=Path, action="append", required=True
    )
    finalize = subparsers.add_parser("finalize")
    finalize.add_argument("--execution-repo", type=Path, required=True)
    finalize.add_argument("--runtime-root", type=Path, required=True)
    finalize.add_argument("--uv-binary", type=Path, required=True)
    finalize.add_argument("--implementation-commit", required=True)
    finalize.add_argument("--checkpoint", type=Path, required=True)
    finalize.add_argument("--expected-checkpoint-sha256", required=True)
    finalize.add_argument("--dataset-manifest", type=Path, required=True)
    finalize.add_argument("--expected-dataset-manifest-sha256", required=True)
    finalize.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "build":
        result = build_isolated_runtime(
            execution_repo=args.execution_repo,
            runtime_root=args.runtime_root,
            uv_binary=args.uv_binary,
            python_binary=args.python_binary,
            protected_roots=tuple(args.protected_root),
        )
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    result = finalize_runtime_contract(
        execution_repo=args.execution_repo,
        runtime_root=args.runtime_root,
        uv_binary=args.uv_binary,
        implementation_commit=args.implementation_commit,
        checkpoint=args.checkpoint,
        expected_checkpoint_sha256=args.expected_checkpoint_sha256,
        dataset_manifest=args.dataset_manifest,
        expected_dataset_manifest_sha256=args.expected_dataset_manifest_sha256,
        output_dir=args.output_dir,
    )
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


__all__ = [
    "build_contract_documents",
    "build_isolated_runtime",
    "current_distribution_rows",
    "directory_contract_sha256",
    "finalize_runtime_contract",
    "isolated_sync_invocation",
    "main",
    "publish_contract_directory",
    "reserve_isolated_runtime_build",
    "validate_contract_documents",
]


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
