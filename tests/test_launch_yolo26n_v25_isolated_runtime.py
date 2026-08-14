from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import scripts.launch_yolo26n_v25_isolated_runtime as launcher


def _private_json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")
    path.chmod(0o600)
    return path


def _fixture(tmp_path: Path) -> dict[str, object]:
    runtime_root = tmp_path / "runtime"
    site = runtime_root / "lib/python3.12/site-packages"
    site.mkdir(parents=True)
    runtime_root.chmod(0o700)
    (site / "package.py").write_bytes(b"approved")
    (site / "__pycache__").mkdir()
    (site / "__pycache__/package.pyc").write_bytes(b"approved-pyc")
    (runtime_root / "bin").mkdir()
    python = tmp_path / "python3.12"
    python.write_bytes(b"python")
    (runtime_root / "bin/python").symlink_to(python)
    uv_lock = tmp_path / "uv.lock"
    uv_lock.write_bytes(b"lock")
    uv_lock.chmod(0o600)
    execution_repo = tmp_path / "repo"
    scripts = execution_repo / "scripts"
    scripts.mkdir(parents=True)
    for relative in launcher._INFERENCE_CODE_BUNDLE:
        path = execution_repo / relative
        path.write_bytes(b"owner" if relative.endswith("v25_owner_hardcase_queue.py") else relative.encode())
    owner = execution_repo / "scripts/build_yolo26n_v25_owner_hardcase_queue.py"
    launcher_code = scripts / "launch_yolo26n_v25_isolated_runtime.py"
    launcher_code.write_bytes(b"launcher")
    code_bundle = {
        relative: hashlib.sha256((execution_repo / relative).read_bytes()).hexdigest()
        for relative in launcher._INFERENCE_CODE_BUNDLE
    }
    scripts_manifest = launcher.scripts_tree_manifest(execution_repo)
    runtime = {
        "python_binary_sha256": hashlib.sha256(b"python").hexdigest(),
        "uv_lock_sha256": hashlib.sha256(b"lock").hexdigest(),
        "site_packages_tree_sha256": launcher.site_packages_tree_sha256(site),
    }
    build = {
        "schema": "yolo26n-v25-isolated-runtime-build-v1",
        "status": "V25_ISOLATED_RUNTIME_READY",
        "runtime": runtime,
        "launcher_code_sha256": hashlib.sha256(b"launcher").hexdigest(),
        "inference_code_sha256": hashlib.sha256(b"owner").hexdigest(),
        "checkpoint_sha256": "a" * 64,
        "dataset_manifest_sha256": "b" * 64,
        "inference_code_bundle": code_bundle,
        "inference_code_bundle_sha256": hashlib.sha256(
            json.dumps(code_bundle, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "inference_scripts_manifest": scripts_manifest,
        "inference_scripts_manifest_sha256": hashlib.sha256(
            json.dumps(
                scripts_manifest, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest(),
    }
    preflight = {
        "schema": "yolo26n-v24b-runtime-preflight-v1",
        "status": "PREFLIGHT_OK",
        "runtime": runtime,
        "code_bundle_sha256": build["inference_code_sha256"],
        "checkpoint_sha256": build["checkpoint_sha256"],
        "dataset_manifest_sha256": build["dataset_manifest_sha256"],
    }
    runtime_build = _private_json(tmp_path / "build.private.json", build)
    runtime_preflight = _private_json(tmp_path / "preflight.private.json", preflight)
    return {
        "runtime_root": runtime_root,
        "execution_repo": execution_repo,
        "runtime_build": runtime_build,
        "expected_runtime_build_sha256": hashlib.sha256(runtime_build.read_bytes()).hexdigest(),
        "runtime_preflight": runtime_preflight,
        "expected_runtime_preflight_sha256": hashlib.sha256(runtime_preflight.read_bytes()).hexdigest(),
        "python_binary": python,
        "uv_lock": uv_lock,
        "owner_code": owner,
        "launcher_code": launcher_code,
        "site": site,
    }


def test_site_tree_hash_includes_pyc_bytes(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    site = paths["site"]
    assert isinstance(site, Path)
    before = launcher.site_packages_tree_sha256(site)
    (site / "__pycache__/package.pyc").write_bytes(b"mutated-pyc")

    assert launcher.site_packages_tree_sha256(site) != before


def test_launcher_verifies_before_exec_and_forces_no_bytecode(
    tmp_path: Path, monkeypatch
) -> None:
    paths = _fixture(tmp_path)
    monkeypatch.setenv("PYTHONPATH", "/attacker")
    monkeypatch.setenv("PYTHONHOME", "/attacker-home")
    command, environment = launcher.prepare_exec(
        **{key: value for key, value in paths.items() if key != "site"},
        inference_args=["infer-build-queue", "--help-contract"],
    )

    assert command[:5] == [
        str(paths["runtime_root"] / "bin/python"),
        "-I",
        "-B",
        "-s",
        "-c",
    ]
    assert environment["PYTHONDONTWRITEBYTECODE"] == "1"
    assert environment["PYTHONNOUSERSITE"] == "1"
    assert "PYTHONPATH" not in environment
    assert "PYTHONHOME" not in environment


def test_launcher_does_not_expose_repo_root_shadow_modules(
    tmp_path: Path,
) -> None:
    paths = _fixture(tmp_path)
    execution_repo = paths["execution_repo"]
    assert isinstance(execution_repo, Path)
    (execution_repo / "numpy.py").write_bytes(b"raise RuntimeError('shadow')\n")

    command, _environment = launcher.prepare_exec(
        **{key: value for key, value in paths.items() if key != "site"},
        inference_args=["infer-build-queue", "--help-contract"],
    )

    assert "repo+'/scripts'" in command[5]
    assert "sys.path.insert(0,repo);" not in command[5]


def test_launcher_rejects_persistent_package_mutation_before_exec(
    tmp_path: Path,
) -> None:
    paths = _fixture(tmp_path)
    site = paths["site"]
    assert isinstance(site, Path)
    (site / "package.py").write_bytes(b"mutated")

    with pytest.raises(ValueError, match="runtime tree"):
        launcher.prepare_exec(
            **{key: value for key, value in paths.items() if key != "site"},
            inference_args=["infer-build-queue", "--help-contract"],
        )


def test_launcher_rejects_nonprivate_runtime_root(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    runtime_root = paths["runtime_root"]
    assert isinstance(runtime_root, Path)
    runtime_root.chmod(0o755)

    with pytest.raises(ValueError, match="runtime root"):
        launcher.prepare_exec(
            **{key: value for key, value in paths.items() if key != "site"},
            inference_args=["infer-build-queue", "--help-contract"],
        )


@pytest.mark.parametrize(
    ("relative_path", "payload"),
    [
        ("scripts/__init__.py", b"raise RuntimeError('untracked package hook')\n"),
        ("scripts/__pycache__/hook.pyc", b"untracked-bytecode"),
    ],
)
def test_launcher_rejects_unpinned_import_affecting_scripts_members(
    tmp_path: Path,
    relative_path: str,
    payload: bytes,
) -> None:
    paths = _fixture(tmp_path)
    execution_repo = paths["execution_repo"]
    assert isinstance(execution_repo, Path)
    injected = execution_repo / relative_path
    injected.parent.mkdir(parents=True, exist_ok=True)
    injected.write_bytes(payload)

    with pytest.raises(ValueError, match="import tree"):
        launcher.prepare_exec(
            **{key: value for key, value in paths.items() if key != "site"},
            inference_args=["infer-build-queue", "--help-contract"],
        )
