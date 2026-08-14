"""Stdlib-only pre-import gate for the private YOLO v2.5 runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import stat
import sys
from pathlib import Path


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_INFERENCE_CODE_BUNDLE = (
    "scripts/build_yolo26n_v25_owner_hardcase_queue.py",
    "scripts/build_yolo26n_v24b_future_holdout.py",
    "scripts/run_yolo26n_v24b_postprocess.py",
    "scripts/select_yolo26n_v24b_postprocess.py",
    "scripts/evaluate_yolo26n_v24b_future_holdout.py",
    "scripts/validate_yolo26n_v24b_future_holdout_export.py",
)


def _read_regular(path: Path, *, private: bool = False) -> bytes:
    descriptor = os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or (
            private and stat.S_IMODE(before.st_mode) != 0o600
        ):
            raise ValueError("isolated launcher regular-file contract mismatch")
        payload = bytearray()
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                raise ValueError("isolated launcher input changed")
            payload.extend(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise ValueError("isolated launcher input changed")
        after = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_mode,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise ValueError("isolated launcher input changed")
        return bytes(payload)
    finally:
        os.close(descriptor)


def _sha(path: Path, *, private: bool = False) -> str:
    return hashlib.sha256(_read_regular(path, private=private)).hexdigest()


def site_packages_tree_sha256(root: Path) -> str:
    metadata = root.lstat()
    if root.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("isolated launcher site-packages contract mismatch")
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        child = path.lstat()
        if stat.S_ISDIR(child.st_mode):
            continue
        if stat.S_ISLNK(child.st_mode) or not stat.S_ISREG(child.st_mode):
            raise ValueError("isolated launcher site-packages contract mismatch")
        relative = path.relative_to(root).as_posix().encode()
        payload = _read_regular(path)
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def _private_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(_read_regular(path, private=True))
    except json.JSONDecodeError:
        raise ValueError("isolated launcher JSON contract mismatch") from None
    if not isinstance(value, dict):
        raise ValueError("isolated launcher JSON contract mismatch")
    return value


def scripts_tree_manifest(execution_repo: Path) -> dict[str, str]:
    """Hash the complete import-visible scripts tree without following links."""
    scripts_root = execution_repo / "scripts"
    root_metadata = scripts_root.lstat()
    if scripts_root.is_symlink() or not stat.S_ISDIR(root_metadata.st_mode):
        raise ValueError("isolated launcher import tree mismatch")
    manifest: dict[str, str] = {}
    pending = [scripts_root]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                path = Path(entry.path)
                metadata = path.lstat()
                if stat.S_ISLNK(metadata.st_mode):
                    raise ValueError("isolated launcher import tree mismatch")
                if stat.S_ISDIR(metadata.st_mode):
                    pending.append(path)
                    continue
                if not stat.S_ISREG(metadata.st_mode):
                    raise ValueError("isolated launcher import tree mismatch")
                relative = path.relative_to(execution_repo).as_posix()
                manifest[relative] = hashlib.sha256(_read_regular(path)).hexdigest()
    return dict(sorted(manifest.items()))


def prepare_exec(
    *,
    runtime_root: Path,
    execution_repo: Path,
    runtime_build: Path,
    expected_runtime_build_sha256: str,
    runtime_preflight: Path,
    expected_runtime_preflight_sha256: str,
    python_binary: Path,
    uv_lock: Path,
    owner_code: Path,
    launcher_code: Path,
    inference_args: list[str],
) -> tuple[list[str], dict[str, str]]:
    if (
        any(
            not path.is_absolute()
            for path in (
                runtime_root,
                execution_repo,
                runtime_build,
                runtime_preflight,
                python_binary,
                uv_lock,
                owner_code,
                launcher_code,
            )
        )
        or not inference_args
        or inference_args[0] != "infer-build-queue"
        or _SHA256.fullmatch(expected_runtime_build_sha256) is None
        or _SHA256.fullmatch(expected_runtime_preflight_sha256) is None
        or _sha(runtime_build, private=True) != expected_runtime_build_sha256
        or _sha(runtime_preflight, private=True)
        != expected_runtime_preflight_sha256
    ):
        raise ValueError("isolated launcher path/command contract mismatch")
    runtime_metadata = runtime_root.lstat()
    if (
        runtime_root.is_symlink()
        or not stat.S_ISDIR(runtime_metadata.st_mode)
        or stat.S_IMODE(runtime_metadata.st_mode) != 0o700
        or runtime_root.resolve(strict=True) != runtime_root
    ):
        raise ValueError("isolated launcher runtime root mismatch")
    build = _private_json(runtime_build)
    preflight = _private_json(runtime_preflight)
    runtime = build.get("runtime")
    code_bundle = build.get("inference_code_bundle")
    approved_scripts = build.get("inference_scripts_manifest")
    if not isinstance(code_bundle, dict) or set(code_bundle) != set(
        _INFERENCE_CODE_BUNDLE
    ):
        raise ValueError("isolated launcher code bundle mismatch")
    actual_code_bundle = {
        relative: _sha(execution_repo / relative)
        for relative in _INFERENCE_CODE_BUNDLE
    }
    actual_code_bundle_sha = hashlib.sha256(
        json.dumps(actual_code_bundle, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    actual_scripts = scripts_tree_manifest(execution_repo)
    actual_scripts_sha = hashlib.sha256(
        json.dumps(actual_scripts, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if (
        not isinstance(approved_scripts, dict)
        or approved_scripts != actual_scripts
        or build.get("inference_scripts_manifest_sha256") != actual_scripts_sha
    ):
        raise ValueError("isolated launcher import tree mismatch")
    if (
        build.get("schema") != "yolo26n-v25-isolated-runtime-build-v1"
        or build.get("status") != "V25_ISOLATED_RUNTIME_READY"
        or not isinstance(runtime, dict)
        or preflight.get("schema") != "yolo26n-v24b-runtime-preflight-v1"
        or preflight.get("status") != "PREFLIGHT_OK"
        or preflight.get("runtime") != runtime
        or build.get("inference_code_sha256") != preflight.get("code_bundle_sha256")
        or build.get("checkpoint_sha256") != preflight.get("checkpoint_sha256")
        or build.get("dataset_manifest_sha256")
        != preflight.get("dataset_manifest_sha256")
        or build.get("launcher_code_sha256") != _sha(launcher_code)
        or build.get("inference_code_sha256") != _sha(owner_code)
        or code_bundle != actual_code_bundle
        or build.get("inference_code_bundle_sha256")
        != actual_code_bundle_sha
        or runtime.get("python_binary_sha256") != _sha(python_binary)
        or runtime.get("uv_lock_sha256") != _sha(uv_lock, private=True)
    ):
        raise ValueError("isolated launcher pin contract mismatch")
    site_packages = runtime_root / "lib/python3.12/site-packages"
    if runtime.get("site_packages_tree_sha256") != site_packages_tree_sha256(
        site_packages
    ):
        raise ValueError("isolated launcher runtime tree mismatch")
    runtime_python = runtime_root / "bin/python"
    if not runtime_python.exists() or _sha(runtime_python.resolve(strict=True)) != runtime.get(
        "python_binary_sha256"
    ):
        raise ValueError("isolated launcher Python capability mismatch")
    capability = {
        "schema": "yolo26n-v25-launch-capability-v1",
        "status": "LAUNCH_VERIFIED",
        "runtime_build_sha256": expected_runtime_build_sha256,
        "runtime_preflight_sha256": expected_runtime_preflight_sha256,
        "inference_code_sha256": str(build["inference_code_sha256"]),
        "inference_code_bundle_sha256": actual_code_bundle_sha,
        "nonce": secrets.token_hex(32),
    }
    read_descriptor, write_descriptor = os.pipe()
    try:
        os.set_inheritable(read_descriptor, True)
        os.write(
            write_descriptor,
            (
                json.dumps(capability, sort_keys=True, separators=(",", ":"))
                + "\n"
            ).encode(),
        )
    finally:
        os.close(write_descriptor)
    return (
        [
            str(runtime_python),
            "-I",
            "-B",
            "-s",
            "-c",
            (
                "import runpy,sys;"
                "repo,owner,*args=sys.argv[1:];"
                "sys.path.insert(0,repo+'/scripts');"
                "sys.argv=[owner,*args];"
                "runpy.run_path(owner,run_name='__main__')"
            ),
            str(execution_repo),
            str(owner_code),
            *inference_args,
        ],
        {
            **{
                key: value
                for key, value in os.environ.items()
                if not key.upper().startswith("PYTHON")
            },
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "V25_LAUNCH_CAPABILITY_FD": str(read_descriptor),
        },
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify an isolated YOLO v2.5 runtime before package import."
    )
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--execution-repo", type=Path, required=True)
    parser.add_argument("--runtime-build", type=Path, required=True)
    parser.add_argument("--expected-runtime-build-sha256", required=True)
    parser.add_argument("--runtime-preflight", type=Path, required=True)
    parser.add_argument("--expected-runtime-preflight-sha256", required=True)
    parser.add_argument("--python-binary", type=Path, required=True)
    parser.add_argument("--uv-lock", type=Path, required=True)
    parser.add_argument("--owner-code", type=Path, required=True)
    parser.add_argument("--launcher-code", type=Path, required=True)
    parser.add_argument("inference_args", nargs=argparse.REMAINDER)
    return parser


def main(argv: list[str] | None = None) -> int:
    if not sys.flags.no_site or not sys.flags.isolated:
        raise ValueError("launcher must run with isolated stdlib-only Python -I -S")
    args = build_parser().parse_args(argv)
    if (
        not Path(sys.executable).samefile(args.python_binary)
        or not Path(__file__).samefile(args.launcher_code)
    ):
        raise ValueError("launcher execution capability mismatch")
    inference_args = list(args.inference_args)
    if inference_args and inference_args[0] == "--":
        inference_args = inference_args[1:]
    command, environment = prepare_exec(
        runtime_root=args.runtime_root,
        execution_repo=args.execution_repo,
        runtime_build=args.runtime_build,
        expected_runtime_build_sha256=args.expected_runtime_build_sha256,
        runtime_preflight=args.runtime_preflight,
        expected_runtime_preflight_sha256=args.expected_runtime_preflight_sha256,
        python_binary=args.python_binary,
        uv_lock=args.uv_lock,
        owner_code=args.owner_code,
        launcher_code=args.launcher_code,
        inference_args=inference_args,
    )
    os.execve(command[0], command, environment)
    return 1  # pragma: no cover - execve never returns


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
