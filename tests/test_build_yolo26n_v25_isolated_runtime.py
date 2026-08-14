from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.build_yolo26n_v25_isolated_runtime as runtime


REPO_ROOT = Path(__file__).resolve().parents[1]


def _runtime_fingerprint(rows: list[tuple[str, str]]) -> dict[str, str]:
    digest = hashlib.sha256()
    for name, version in sorted(rows):
        digest.update(f"{name}=={version}\n".encode())
    return {
        "python_binary_sha256": "1" * 64,
        "uv_lock_sha256": "2" * 64,
        "distributions_sha256": digest.hexdigest(),
        "site_packages_tree_sha256": "c" * 64,
        "ultralytics_version": "8.4.104",
        "ultralytics_tree_sha256": "3" * 64,
        "torch_version": "2.12.0",
        "torch_tree_sha256": "8" * 64,
        "torchvision_version": "0.27.0",
        "torchvision_tree_sha256": "9" * 64,
        "numpy_version": "2.4.4",
        "numpy_tree_sha256": "a" * 64,
        "opencv_version": "5.0.0",
        "opencv_tree_sha256": "7" * 64,
        "pillow_version": "12.2.0",
        "pillow_tree_sha256": "b" * 64,
    }


def _rows() -> list[tuple[str, str]]:
    return [
        ("numpy", "2.4.4"),
        ("opencv-python", "5.0.0.93"),
        ("pillow", "12.2.0"),
        ("torch", "2.12.0"),
        ("torchvision", "0.27.0"),
        ("ultralytics", "8.4.104"),
    ]


def _protected_roots(tmp_path: Path) -> tuple[Path, ...]:
    roots = tuple(tmp_path / f"shared-{index:02d}" for index in range(25))
    for root in roots:
        root.mkdir()
    return roots


def _python_binary(tmp_path: Path) -> Path:
    path = tmp_path / "python3.12"
    if not path.exists():
        path.write_bytes(b"python")
    return path


def _write_started_contract(
    parent: Path,
    *,
    runtime_root: Path,
    uv_lock_sha256: str,
    uv_binary_sha256: str = "9" * 64,
    python_binary_sha256: str = "1" * 64,
) -> None:
    payload = {
        "schema": "yolo26n-v25-isolated-runtime-started-v1",
        "status": "STARTED",
        "runtime_root": str(runtime_root),
        "uv_lock_sha256": uv_lock_sha256,
        "uv_binary_sha256": uv_binary_sha256,
        "python_binary_sha256": python_binary_sha256,
        "protected_root_count": 25,
        "protected_inventory_sha256": "c" * 64,
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
        "production_model_write_count": 0,
        "gme_write_count": 0,
        "labeling_web_write_count": 0,
    }
    path = parent / "runtime-build.started.private.json"
    path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    path.chmod(0o600)


def test_train_group_is_exact_and_lock_reproducible() -> None:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())

    assert pyproject["dependency-groups"]["train"] == [
        "numpy==2.4.4",
        "pillow==12.2.0",
        "torch==2.12.0",
        "torchvision==0.27.0",
        "ultralytics==8.4.104",
    ]
    lock_text = (REPO_ROOT / "uv.lock").read_text()
    for name, version in (
        ("opencv-python", "5.0.0.93"),
        ("torchvision", "0.27.0"),
        ("ultralytics", "8.4.104"),
    ):
        assert f'name = "{name}"' in lock_text
        assert f'version = "{version}"' in lock_text


def test_sync_invocation_is_frozen_train_only_and_private(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    runtime_root = tmp_path / "private" / "runtime"
    runtime_root.parent.mkdir()
    runtime_root.parent.chmod(0o700)
    uv = tmp_path / "uv"
    uv.write_bytes(b"uv")
    python = _python_binary(tmp_path)
    protected = tmp_path / "shared-venv"
    protected.mkdir()

    command, environment = runtime.isolated_sync_invocation(
        execution_repo=repo,
        runtime_root=runtime_root,
        uv_binary=uv,
        python_binary=python,
        protected_roots=(protected,),
    )

    assert command == (
        str(uv),
        "sync",
        "--frozen",
        "--only-group",
        "train",
        "--no-install-project",
        "--python",
        str(python),
        "--project",
        str(repo),
    )
    assert environment == {
        "UV_PROJECT_ENVIRONMENT": str(runtime_root),
        "UV_NO_PROGRESS": "1",
        "UV_PYTHON_DOWNLOADS": "never",
    }
    assert "pip" not in command


@pytest.mark.parametrize("placement", ["repo", "shared", "existing"])
def test_sync_invocation_rejects_shared_or_nonfresh_targets(
    tmp_path: Path, placement: str
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    shared = tmp_path / "shared"
    shared.mkdir()
    runtime_root = {
        "repo": repo / ".venv",
        "shared": shared / "child",
        "existing": tmp_path / "existing",
    }[placement]
    if placement == "existing":
        runtime_root.mkdir()
    uv = tmp_path / "uv"
    uv.write_bytes(b"uv")

    with pytest.raises(ValueError, match="isolated runtime target contract"):
        runtime.isolated_sync_invocation(
            execution_repo=repo,
            runtime_root=runtime_root,
            uv_binary=uv,
            python_binary=_python_binary(tmp_path),
            protected_roots=(shared,),
        )


def test_sync_invocation_rejects_symlink_parent_escape(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    private_parent = tmp_path / "private"
    private_parent.mkdir()
    shared = tmp_path / "shared"
    shared.mkdir()
    (private_parent / "jump").symlink_to(shared, target_is_directory=True)
    uv = tmp_path / "uv"
    uv.write_bytes(b"uv")

    with pytest.raises(ValueError, match="isolated runtime target contract"):
        runtime.isolated_sync_invocation(
            execution_repo=repo,
            runtime_root=private_parent / "jump" / "runtime",
            uv_binary=uv,
            python_binary=_python_binary(tmp_path),
            protected_roots=(shared,),
        )


def test_sync_invocation_rejects_execution_repo_alias_escape(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    alias = tmp_path / "repo-alias"
    alias.symlink_to(repo, target_is_directory=True)
    uv = tmp_path / "uv"
    uv.write_bytes(b"uv")
    protected = tmp_path / "shared"
    protected.mkdir()

    with pytest.raises(ValueError, match="isolated runtime target contract"):
        runtime.isolated_sync_invocation(
            execution_repo=alias,
            runtime_root=repo / "runtime",
            uv_binary=uv,
            python_binary=_python_binary(tmp_path),
            protected_roots=(protected,),
        )


def test_runtime_build_reservation_is_atomic_private_and_copies_lock(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "uv.lock").write_bytes(b"locked")
    attempt = tmp_path / "attempt"
    attempt.mkdir(mode=0o700)
    runtime_root = attempt / "runtime"
    uv = tmp_path / "uv"
    uv.write_bytes(b"uv")
    protected = _protected_roots(tmp_path)

    command, environment, identity = runtime.reserve_isolated_runtime_build(
        execution_repo=repo,
        runtime_root=runtime_root,
        uv_binary=uv,
        python_binary=_python_binary(tmp_path),
        protected_roots=protected,
    )

    assert command[0] == str(uv)
    assert environment["UV_PROJECT_ENVIRONMENT"] == str(runtime_root)
    assert identity[:3] == (
        runtime_root.stat().st_dev,
        runtime_root.stat().st_ino,
        runtime_root.stat().st_mode,
    )
    assert (runtime_root.stat().st_mode & 0o777) == 0o700
    assert (attempt / "uv.lock").read_bytes() == b"locked"
    assert ((attempt / "uv.lock").stat().st_mode & 0o777) == 0o600
    started = attempt / "runtime-build.started.private.json"
    assert (started.stat().st_mode & 0o777) == 0o600
    with pytest.raises((FileExistsError, ValueError)):
        runtime.reserve_isolated_runtime_build(
            execution_repo=repo,
            runtime_root=runtime_root,
            uv_binary=uv,
            python_binary=_python_binary(tmp_path),
            protected_roots=protected,
        )


def test_build_operation_runs_uv_only_after_owned_reservation(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "uv.lock").write_bytes(b"locked")
    attempt = tmp_path / "attempt"
    attempt.mkdir(mode=0o700)
    runtime_root = attempt / "runtime"
    uv = tmp_path / "uv"
    uv.write_bytes(b"uv")
    protected = _protected_roots(tmp_path)

    def runner(command, **kwargs):
        assert command[0] == str(uv)
        assert runtime_root.is_dir()
        assert (attempt / "runtime-build.started.private.json").is_file()
        assert kwargs["env"]["UV_PROJECT_ENVIRONMENT"] == str(runtime_root)
        (runtime_root / "installed").write_bytes(b"ok")
        return SimpleNamespace(returncode=0)

    result = runtime.build_isolated_runtime(
        execution_repo=repo,
        runtime_root=runtime_root,
        uv_binary=uv,
        python_binary=_python_binary(tmp_path),
        protected_roots=protected,
        runner=runner,
    )

    assert result == {"status": "V25_ISOLATED_RUNTIME_SYNCED"}


def test_build_operation_rejects_started_lock_aba_and_preserves_rival(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "uv.lock").write_bytes(b"locked")
    attempt = tmp_path / "attempt"
    attempt.mkdir(mode=0o700)
    runtime_root = attempt / "runtime"
    uv = tmp_path / "uv"
    uv.write_bytes(b"uv")
    protected = _protected_roots(tmp_path)
    moved = attempt / "moved-started"

    def runner(_command, **_kwargs):
        started = attempt / "runtime-build.started.private.json"
        started.rename(moved)
        started.write_bytes(b"third-party")
        started.chmod(0o600)
        return SimpleNamespace(returncode=0)

    with pytest.raises(ValueError, match="changed during sync"):
        runtime.build_isolated_runtime(
            execution_repo=repo,
            runtime_root=runtime_root,
            uv_binary=uv,
            python_binary=_python_binary(tmp_path),
            protected_roots=protected,
            runner=runner,
        )
    assert (attempt / "runtime-build.started.private.json").read_bytes() == b"third-party"
    assert moved.is_file()


def test_build_operation_rejects_shared_runtime_mutation(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "uv.lock").write_bytes(b"locked")
    attempt = tmp_path / "attempt"
    attempt.mkdir(mode=0o700)
    runtime_root = attempt / "runtime"
    uv = tmp_path / "uv"
    uv.write_bytes(b"uv")
    protected = _protected_roots(tmp_path)
    watched = protected[0] / "marker"
    watched.write_bytes(b"before")

    def runner(_command, **_kwargs):
        watched.write_bytes(b"after")
        return SimpleNamespace(returncode=0)

    with pytest.raises(ValueError, match="changed during sync"):
        runtime.build_isolated_runtime(
            execution_repo=repo,
            runtime_root=runtime_root,
            uv_binary=uv,
            python_binary=_python_binary(tmp_path),
            protected_roots=protected,
            runner=runner,
        )


def test_sync_check_is_exact_nonmutating_and_uses_reserved_runtime(
    tmp_path: Path, monkeypatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    runtime_root.chmod(0o700)
    uv = tmp_path / "uv"
    uv.write_bytes(b"uv")
    calls: list[tuple[object, dict[str, object]]] = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(runtime.subprocess, "run", fake_run)
    digest = runtime._assert_runtime_synchronized(
        execution_repo=repo, runtime_root=runtime_root, uv_binary=uv
    )

    assert digest == hashlib.sha256(b"uv").hexdigest()
    command, kwargs = calls[0]
    assert command[-1] == "--check"
    assert "--frozen" in command
    assert command[command.index("--only-group") + 1] == "train"
    assert "--no-install-project" in command
    assert kwargs["env"]["UV_PROJECT_ENVIRONMENT"] == str(runtime_root)


def test_contract_records_full_distribution_manifest_and_compatibility_projection() -> None:
    rows = _rows()
    fingerprint = _runtime_fingerprint(rows)

    build, preflight = runtime.build_contract_documents(
        implementation_commit="a" * 40,
        pyproject_sha256="b" * 64,
        uv_lock_sha256="2" * 64,
        builder_code_sha256="c" * 64,
        inference_code_sha256="f" * 64,
        checkpoint_sha256="d" * 64,
        dataset_manifest_sha256="e" * 64,
        python_version="3.12.11",
        runtime_fingerprint=fingerprint,
        distributions=rows,
    )

    assert build["schema"] == "yolo26n-v25-isolated-runtime-build-v1"
    assert build["status"] == "V25_ISOLATED_RUNTIME_READY"
    assert build["distribution_count"] == 6
    assert build["distributions"] == [
        {"name": name, "version": version} for name, version in sorted(rows)
    ]
    assert build["sync_contract"] == {
        "dependency_group": "train",
        "frozen": True,
        "only_group": True,
        "no_install_project": True,
        "python": "3.12",
    }
    assert preflight["schema"] == "yolo26n-v24b-runtime-preflight-v1"
    assert preflight["status"] == "PREFLIGHT_OK"
    assert preflight["runtime"] == fingerprint
    assert preflight["checkpoint_sha256"] == "d" * 64


@pytest.mark.parametrize(
    "mutation",
    [
        lambda rows: rows + [("attacker-package", "1.0")],
        lambda rows: rows[:-1],
        lambda rows: [*rows[:-1], ("ultralytics", "8.4.105")],
    ],
)
def test_contract_validation_rejects_distribution_drift(mutation) -> None:
    rows = _rows()
    fingerprint = _runtime_fingerprint(rows)
    build, preflight = runtime.build_contract_documents(
        implementation_commit="a" * 40,
        pyproject_sha256="b" * 64,
        uv_lock_sha256="2" * 64,
        builder_code_sha256="c" * 64,
        inference_code_sha256="f" * 64,
        checkpoint_sha256="d" * 64,
        dataset_manifest_sha256="e" * 64,
        python_version="3.12.11",
        runtime_fingerprint=fingerprint,
        distributions=rows,
    )

    with pytest.raises(ValueError, match="isolated runtime drift"):
        runtime.validate_contract_documents(
            build=build,
            preflight=preflight,
            current_runtime_fingerprint=_runtime_fingerprint(mutation(rows)),
            current_distributions=mutation(rows),
        )


def test_build_contract_rejects_multiple_opencv_wheel_families() -> None:
    rows = [*_rows(), ("opencv-contrib-python-headless", "4.13.0.92")]
    with pytest.raises(ValueError, match="isolated runtime build contract"):
        runtime.build_contract_documents(
            implementation_commit="a" * 40,
            pyproject_sha256="b" * 64,
            uv_lock_sha256="2" * 64,
            builder_code_sha256="c" * 64,
            inference_code_sha256="f" * 64,
            checkpoint_sha256="d" * 64,
            dataset_manifest_sha256="e" * 64,
            python_version="3.12.11",
            runtime_fingerprint=_runtime_fingerprint(rows),
            distributions=rows,
        )


def test_contract_directory_is_private_no_overwrite(tmp_path: Path) -> None:
    rows = _rows()
    build, preflight = runtime.build_contract_documents(
        implementation_commit="a" * 40,
        pyproject_sha256="b" * 64,
        uv_lock_sha256="2" * 64,
        builder_code_sha256="c" * 64,
        inference_code_sha256="f" * 64,
        checkpoint_sha256="d" * 64,
        dataset_manifest_sha256="e" * 64,
        python_version="3.12.11",
        runtime_fingerprint=_runtime_fingerprint(rows),
        distributions=rows,
    )
    output = tmp_path / "runtime-contract"

    digest = runtime.publish_contract_directory(
        build=build, preflight=preflight, output_dir=output
    )

    assert digest == runtime.directory_contract_sha256(output)
    assert json.loads((output / "runtime-build.private.json").read_bytes()) == build
    assert json.loads((output / "runtime-preflight.private.json").read_bytes()) == preflight
    assert (output.stat().st_mode & 0o777) == 0o700
    assert all((path.stat().st_mode & 0o777) == 0o600 for path in output.iterdir())
    with pytest.raises(FileExistsError):
        runtime.publish_contract_directory(
            build=build, preflight=preflight, output_dir=output
        )


def test_current_distribution_rows_are_canonical_and_complete(monkeypatch) -> None:
    fake = [
        SimpleNamespace(metadata={"Name": "Ultralytics"}, version="8.4.104"),
        SimpleNamespace(metadata={"Name": "numpy"}, version="2.4.4"),
    ]
    monkeypatch.setattr(runtime.importlib.metadata, "distributions", lambda: fake)

    assert runtime.current_distribution_rows() == [
        ("numpy", "2.4.4"),
        ("ultralytics", "8.4.104"),
    ]


def test_preflight_code_bundle_is_exact_inference_code_sha() -> None:
    rows = _rows()
    build, preflight = runtime.build_contract_documents(
        implementation_commit="a" * 40,
        pyproject_sha256="b" * 64,
        uv_lock_sha256="2" * 64,
        builder_code_sha256="c" * 64,
        inference_code_sha256="f" * 64,
        checkpoint_sha256="d" * 64,
        dataset_manifest_sha256="e" * 64,
        python_version="3.12.11",
        runtime_fingerprint=_runtime_fingerprint(rows),
        distributions=rows,
    )

    assert build["inference_code_sha256"] == "f" * 64
    assert preflight["code_bundle_sha256"] == "f" * 64


def test_finalize_recalculates_runtime_and_publishes_once(
    tmp_path: Path, monkeypatch
) -> None:
    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    scripts.mkdir(parents=True)
    (repo / "pyproject.toml").write_text("[project]\nname='x'\n")
    (repo / "uv.lock").write_text("version = 1\n")
    (scripts / "build_yolo26n_v25_isolated_runtime.py").write_bytes(b"builder")
    (scripts / "build_yolo26n_v25_owner_hardcase_queue.py").write_bytes(b"infer")
    (scripts / "launch_yolo26n_v25_isolated_runtime.py").write_bytes(b"launcher")
    for relative in runtime._INFERENCE_CODE_BUNDLE:
        path = repo / relative
        if not path.exists():
            path.write_bytes(relative.encode())
    checkpoint = tmp_path / "checkpoint.pt"
    checkpoint.write_bytes(b"checkpoint")
    dataset = tmp_path / "dataset.json"
    dataset.write_bytes(b"dataset")
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    runtime_root.chmod(0o700)
    rows = _rows()
    fingerprint = _runtime_fingerprint(rows)
    fingerprint["uv_lock_sha256"] = hashlib.sha256(
        (repo / "uv.lock").read_bytes()
    ).hexdigest()
    (tmp_path / "uv.lock").write_bytes((repo / "uv.lock").read_bytes())
    (tmp_path / "uv.lock").chmod(0o600)
    _write_started_contract(
        tmp_path,
        runtime_root=runtime_root,
        uv_lock_sha256=fingerprint["uv_lock_sha256"],
    )
    monkeypatch.setattr(runtime.sys, "prefix", str(runtime_root))
    monkeypatch.setattr(runtime, "_git_state", lambda _repo: ("a" * 40, True))
    monkeypatch.setattr(
        runtime, "_approved_scripts_manifest", runtime._scripts_tree_manifest
    )
    monkeypatch.setattr(runtime, "_assert_runtime_synchronized", lambda **_kwargs: "9" * 64)
    monkeypatch.setattr(runtime, "current_distribution_rows", lambda: rows)
    monkeypatch.setattr(runtime, "current_runtime_fingerprint", lambda: fingerprint)
    output = tmp_path / "contract"

    result = runtime.finalize_runtime_contract(
        execution_repo=repo,
        runtime_root=runtime_root,
        uv_binary=tmp_path / "uv",
        implementation_commit="a" * 40,
        checkpoint=checkpoint,
        expected_checkpoint_sha256=hashlib.sha256(b"checkpoint").hexdigest(),
        dataset_manifest=dataset,
        expected_dataset_manifest_sha256=hashlib.sha256(b"dataset").hexdigest(),
        output_dir=output,
    )

    assert result["status"] == "V25_ISOLATED_RUNTIME_READY"
    assert result["distribution_count"] == 6
    assert result["contract_sha256"] == runtime.directory_contract_sha256(output)
    assert result["runtime_preflight_sha256"] == hashlib.sha256(
        (output / "runtime-preflight.private.json").read_bytes()
    ).hexdigest()


def test_finalize_rejects_runtime_drift_before_publication(
    tmp_path: Path, monkeypatch
) -> None:
    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    scripts.mkdir(parents=True)
    for relative, payload in (
        ("pyproject.toml", b"project"),
        ("uv.lock", b"lock"),
        ("scripts/build_yolo26n_v25_isolated_runtime.py", b"builder"),
        ("scripts/build_yolo26n_v25_owner_hardcase_queue.py", b"infer"),
        ("scripts/launch_yolo26n_v25_isolated_runtime.py", b"launcher"),
    ):
        (repo / relative).write_bytes(payload)
    for relative in runtime._INFERENCE_CODE_BUNDLE:
        path = repo / relative
        if not path.exists():
            path.write_bytes(relative.encode())
    checkpoint = tmp_path / "checkpoint.pt"
    checkpoint.write_bytes(b"checkpoint")
    dataset = tmp_path / "dataset.json"
    dataset.write_bytes(b"dataset")
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    runtime_root.chmod(0o700)
    rows = _rows()
    approved = _runtime_fingerprint(rows)
    approved["uv_lock_sha256"] = hashlib.sha256(b"lock").hexdigest()
    (tmp_path / "uv.lock").write_bytes(b"lock")
    (tmp_path / "uv.lock").chmod(0o600)
    _write_started_contract(
        tmp_path,
        runtime_root=runtime_root,
        uv_lock_sha256=approved["uv_lock_sha256"],
    )
    drifted = dict(approved, ultralytics_version="8.4.105")
    probes = iter((approved, drifted))
    monkeypatch.setattr(runtime.sys, "prefix", str(runtime_root))
    monkeypatch.setattr(runtime, "_git_state", lambda _repo: ("a" * 40, True))
    monkeypatch.setattr(
        runtime, "_approved_scripts_manifest", runtime._scripts_tree_manifest
    )
    monkeypatch.setattr(runtime, "_assert_runtime_synchronized", lambda **_kwargs: "9" * 64)
    monkeypatch.setattr(runtime, "current_distribution_rows", lambda: rows)
    monkeypatch.setattr(runtime, "current_runtime_fingerprint", lambda: next(probes))
    output = tmp_path / "contract"

    with pytest.raises(ValueError, match="changed during finalization"):
        runtime.finalize_runtime_contract(
            execution_repo=repo,
            runtime_root=runtime_root,
            uv_binary=tmp_path / "uv",
            implementation_commit="a" * 40,
            checkpoint=checkpoint,
            expected_checkpoint_sha256=hashlib.sha256(b"checkpoint").hexdigest(),
            dataset_manifest=dataset,
            expected_dataset_manifest_sha256=hashlib.sha256(b"dataset").hexdigest(),
            output_dir=output,
        )
    assert not output.exists()


def test_finalize_cli_is_explicit_and_prints_safe_aggregate(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    expected = {
        "status": "V25_ISOLATED_RUNTIME_READY",
        "distribution_count": 117,
        "contract_sha256": "a" * 64,
        "runtime_preflight_sha256": "b" * 64,
    }
    captured: dict[str, object] = {}

    def fake_finalize(**kwargs):
        captured.update(kwargs)
        return expected

    monkeypatch.setattr(runtime, "finalize_runtime_contract", fake_finalize)
    paths = {
        "execution_repo": tmp_path / "repo",
        "runtime_root": tmp_path / "runtime",
        "uv_binary": tmp_path / "uv",
        "checkpoint": tmp_path / "checkpoint.pt",
        "dataset_manifest": tmp_path / "dataset.json",
        "output_dir": tmp_path / "contract",
    }
    argv = [
        "finalize",
        "--execution-repo",
        str(paths["execution_repo"]),
        "--runtime-root",
        str(paths["runtime_root"]),
        "--uv-binary",
        str(paths["uv_binary"]),
        "--implementation-commit",
        "c" * 40,
        "--checkpoint",
        str(paths["checkpoint"]),
        "--expected-checkpoint-sha256",
        "d" * 64,
        "--dataset-manifest",
        str(paths["dataset_manifest"]),
        "--expected-dataset-manifest-sha256",
        "e" * 64,
        "--output-dir",
        str(paths["output_dir"]),
    ]

    assert runtime.main(argv) == 0
    assert json.loads(capsys.readouterr().out) == expected
    assert captured == {
        **paths,
        "implementation_commit": "c" * 40,
        "expected_checkpoint_sha256": "d" * 64,
        "expected_dataset_manifest_sha256": "e" * 64,
    }


def test_contract_publication_quarantines_owned_late_mutation(
    tmp_path: Path, monkeypatch
) -> None:
    rows = _rows()
    build, preflight = runtime.build_contract_documents(
        implementation_commit="a" * 40,
        pyproject_sha256="b" * 64,
        uv_lock_sha256="2" * 64,
        builder_code_sha256="c" * 64,
        inference_code_sha256="f" * 64,
        checkpoint_sha256="d" * 64,
        dataset_manifest_sha256="e" * 64,
        python_version="3.12.11",
        runtime_fingerprint=_runtime_fingerprint(rows),
        distributions=rows,
    )
    output = tmp_path / "runtime-contract"
    real_publish = runtime._publish_verified_directory_new

    def publish_then_mutate(staging, destination, expected_identity):
        real_publish(staging, destination, expected_identity)
        (destination / "runtime-build.private.json").write_bytes(b"rival")

    monkeypatch.setattr(
        runtime, "_publish_verified_directory_new", publish_then_mutate
    )

    with pytest.raises(ValueError, match="publication drift"):
        runtime.publish_contract_directory(
            build=build, preflight=preflight, output_dir=output
        )
    assert not output.exists()


def test_contract_publication_restores_rival_regular_root(
    tmp_path: Path, monkeypatch
) -> None:
    rows = _rows()
    build, preflight = runtime.build_contract_documents(
        implementation_commit="a" * 40,
        pyproject_sha256="b" * 64,
        uv_lock_sha256="2" * 64,
        builder_code_sha256="c" * 64,
        inference_code_sha256="f" * 64,
        checkpoint_sha256="d" * 64,
        dataset_manifest_sha256="e" * 64,
        python_version="3.12.11",
        runtime_fingerprint=_runtime_fingerprint(rows),
        distributions=rows,
    )
    output = tmp_path / "runtime-contract"
    moved_owned = tmp_path / "moved-owned"
    real_publish = runtime._publish_verified_directory_new

    def publish_then_replace(staging, destination, expected_identity):
        real_publish(staging, destination, expected_identity)
        destination.rename(moved_owned)
        destination.write_bytes(b"third-party")
        destination.chmod(0o600)

    monkeypatch.setattr(
        runtime, "_publish_verified_directory_new", publish_then_replace
    )

    with pytest.raises(ValueError):
        runtime.publish_contract_directory(
            build=build, preflight=preflight, output_dir=output
        )
    assert output.read_bytes() == b"third-party"
    assert moved_owned.is_dir()


def test_contract_publication_rejects_symlink_parent_escape(
    tmp_path: Path,
) -> None:
    shared = tmp_path / "shared"
    shared.mkdir(mode=0o700)
    jump = tmp_path / "jump"
    jump.symlink_to(shared, target_is_directory=True)
    rows = _rows()
    build, preflight = runtime.build_contract_documents(
        implementation_commit="a" * 40,
        pyproject_sha256="b" * 64,
        uv_lock_sha256="2" * 64,
        builder_code_sha256="c" * 64,
        inference_code_sha256="f" * 64,
        checkpoint_sha256="d" * 64,
        dataset_manifest_sha256="e" * 64,
        python_version="3.12.11",
        runtime_fingerprint=_runtime_fingerprint(rows),
        distributions=rows,
    )

    with pytest.raises(ValueError, match="publication path"):
        runtime.publish_contract_directory(
            build=build,
            preflight=preflight,
            output_dir=jump / "runtime-contract",
        )
    assert not (shared / "runtime-contract").exists()
