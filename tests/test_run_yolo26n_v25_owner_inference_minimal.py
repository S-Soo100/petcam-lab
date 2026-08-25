from __future__ import annotations

import hashlib
import io
import json
import stat
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from scripts import run_yolo26n_v25_owner_inference_minimal as runner


class _Tensor:
    def __init__(self, value: list[object]) -> None:
        self._value = value

    def cpu(self) -> _Tensor:
        return self

    def tolist(self) -> list[object]:
        return self._value


class _Boxes:
    def __init__(self) -> None:
        self.xyxy = _Tensor([])
        self.conf = _Tensor([])


class _Result:
    path = "image0.jpg"
    orig_shape = (12, 16)
    boxes = _Boxes()


class _Model:
    def __init__(self, *, fail_call: int | None = None) -> None:
        self.calls = 0
        self.fail_call = fail_call
        self.kwargs: list[dict[str, object]] = []

    def predict(self, **kwargs: object) -> list[_Result]:
        self.calls += 1
        self.kwargs.append(dict(kwargs))
        if self.calls == self.fail_call:
            raise RuntimeError("single frame failed")
        return [_Result()]


def _jpeg() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (16, 12), (12, 34, 56)).save(output, format="JPEG")
    return output.getvalue()


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _directory_sha(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode()
        metadata = path.lstat()
        digest.update(relative)
        if stat.S_ISDIR(metadata.st_mode):
            digest.update(b"\0D\0")
        elif stat.S_ISREG(metadata.st_mode):
            digest.update(b"\0F\0")
            digest.update(path.read_bytes())
        else:
            raise AssertionError("test bundle must contain only directories/files")
    return digest.hexdigest()


@pytest.fixture(scope="module")
def accepted_bundle(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, str]:
    root = tmp_path_factory.mktemp("accepted") / "dedup-frame-bundle"
    images = root / "images"
    images.mkdir(parents=True, mode=0o700)
    payload = _jpeg()
    image_sha = hashlib.sha256(payload).hexdigest()
    records: list[dict[str, object]] = []
    for index in range(1, 281):
        filename = f"F{index:06d}.jpg"
        path = images / filename
        path.write_bytes(payload)
        path.chmod(0o600)
        records.append(
            {
                "role": "owner-development-video",
                "source_video_sha256": hashlib.sha256(
                    f"source-{(index - 1) % 35}".encode()
                ).hexdigest(),
                "frame_index": index,
                "timestamp_sec": float(index),
                "image_sha256": image_sha,
                "dhash64": "0" * 16,
                "width": 16,
                "height": 12,
                "selection_reasons": ["uniform"],
                "filename": filename,
            }
        )
    manifest = {
        "schema": "yolo26n-v25-dedup-frame-bundle-v1",
        "status": "V25_DEDUP_FRAME_BUNDLE_READY",
        "role": "owner-development-video",
        "record_count": 280,
        "provenance": {
            "input_audit_sha256": "1" * 64,
            "historical_fingerprint_sha256": "2" * 64,
            "code_sha256": "3" * 64,
            "dedup_ledger_sha256": "4" * 64,
        },
        "records": records,
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
    }
    manifest_path = root / "manifest.private.json"
    manifest_path.write_bytes(_json_bytes(manifest))
    manifest_path.chmod(0o600)
    root.chmod(0o700)
    images.chmod(0o700)
    return root, _directory_sha(root)


def _private_file(path: Path, payload: bytes) -> tuple[Path, str]:
    path.write_bytes(payload)
    path.chmod(0o600)
    return path, hashlib.sha256(payload).hexdigest()


def _freeze(tmp_path: Path, checkpoint_sha: str) -> tuple[Path, str]:
    return _private_file(
        tmp_path / "freeze.private.json",
        _json_bytes(
            {
                "schema": "yolo26n-v24b-postprocess-freeze-v1",
                "status": "V24B_POSTPROCESS_FROZEN_DEVELOPMENT_ONLY",
                "checkpoint_sha256": checkpoint_sha,
                "selected": {"confidence": 0.25, "nms_iou": 0.4, "duplicate": 4},
                "db_write_count": 0,
                "r2_write_count": 0,
                "service_write_count": 0,
                "git_write_count": 0,
            }
        ),
    )


def _run(
    tmp_path: Path,
    accepted_bundle: tuple[Path, str],
    *,
    model: _Model | None = None,
) -> tuple[dict[str, object], _Model]:
    bundle, bundle_sha = accepted_bundle
    checkpoint, checkpoint_sha = _private_file(tmp_path / "best.pt", b"checkpoint")
    freeze, freeze_sha = _freeze(tmp_path, checkpoint_sha)
    used_model = model or _Model()
    result = runner.run_minimal_owner_inference(
        bundle_dir=bundle,
        expected_bundle_sha256=bundle_sha,
        checkpoint=checkpoint,
        expected_checkpoint_sha256=checkpoint_sha,
        freeze=freeze,
        expected_freeze_sha256=freeze_sha,
        output_root=tmp_path / "attempt",
        model_factory=lambda capability: (
            used_model
            if capability.sha256 == checkpoint_sha and capability.payload == b"checkpoint"
            else (_ for _ in ()).throw(AssertionError("unverified checkpoint"))
        ),
        runtime_probe=lambda: {
            "python": "3.12.test",
            "ultralytics": "test",
            "torch": "test",
            "torchvision": "test",
            "numpy": "test",
            "opencv": "test",
            "pillow": "test",
        },
    )
    return result, used_model


def test_runner_completes_280_to_210_queue_and_existing_validator_accepts(
    tmp_path: Path, accepted_bundle: tuple[Path, str]
) -> None:
    result, model = _run(tmp_path, accepted_bundle)

    assert result["status"] == "V25_BLIND_CVAT_QUEUE_READY"
    assert result["input_count"] == 280
    assert result["selected_count"] == 210
    assert result["source_video_count"] == 35
    assert model.calls == 280
    assert all(
        call["conf"] == 0.25
        and call["iou"] == 0.40
        and call["imgsz"] == 960
        and call["max_det"] == 50
        and call["save"] is False
        and call["stream"] is False
        for call in model.kwargs
    )
    attempt = tmp_path / "attempt"
    assert (attempt / "acceptance.private.json").is_file()
    assert (attempt / "blind-queue" / "cvat-upload.zip").is_file()
    assert all(
        stat.S_IMODE(path.lstat().st_mode) == (0o700 if path.is_dir() else 0o600)
        for path in attempt.rglob("*")
    )


def test_runner_records_separate_producer_and_inference_code_sha_and_warnings(
    tmp_path: Path, accepted_bundle: tuple[Path, str]
) -> None:
    _run(tmp_path, accepted_bundle)
    ledger = json.loads((tmp_path / "attempt" / "provenance-ledger.private.json").read_bytes())

    assert ledger["producer_code_sha256"] == "3" * 64
    assert ledger["inference_code_sha256"] != ledger["producer_code_sha256"]
    assert ledger["runtime_versions"]["python"] == "3.12.test"
    assert ledger["gate_policy"] == "quarantine_all"
    assert ledger["gate_candidate_count"] == 0
    assert ledger["gate_inputs_consumed"] is False
    assert ledger["protected_access_count"] == 0
    assert all(
        ledger[key] == 0
        for key in (
            "db_write_count",
            "r2_write_count",
            "service_write_count",
            "production_model_write_count",
            "gme_write_count",
            "labeling_web_write_count",
            "deploy_count",
        )
    )


def test_runner_rejects_bundle_or_freeze_pin_before_model_load(
    tmp_path: Path, accepted_bundle: tuple[Path, str]
) -> None:
    bundle, _bundle_sha = accepted_bundle
    checkpoint, checkpoint_sha = _private_file(tmp_path / "best.pt", b"checkpoint")
    freeze, freeze_sha = _freeze(tmp_path, checkpoint_sha)
    called = False

    def factory(_capability: object) -> object:
        nonlocal called
        called = True
        return _Model()

    with pytest.raises(ValueError, match="bundle"):
        runner.run_minimal_owner_inference(
            bundle_dir=bundle,
            expected_bundle_sha256="0" * 64,
            checkpoint=checkpoint,
            expected_checkpoint_sha256=checkpoint_sha,
            freeze=freeze,
            expected_freeze_sha256=freeze_sha,
            output_root=tmp_path / "bundle-reject",
            model_factory=factory,
            runtime_probe=lambda: {},
        )
    payload = json.loads(freeze.read_bytes())
    payload["selected"]["duplicate"] = 3
    freeze.write_bytes(_json_bytes(payload))
    freeze.chmod(0o600)
    with pytest.raises(ValueError, match="freeze"):
        runner.run_minimal_owner_inference(
            bundle_dir=bundle,
            expected_bundle_sha256=accepted_bundle[1],
            checkpoint=checkpoint,
            expected_checkpoint_sha256=checkpoint_sha,
            freeze=freeze,
            expected_freeze_sha256=hashlib.sha256(freeze.read_bytes()).hexdigest(),
            output_root=tmp_path / "freeze-reject",
            model_factory=factory,
            runtime_probe=lambda: {},
        )
    assert called is False


def test_runner_excludes_one_inference_failure_and_continues(
    tmp_path: Path, accepted_bundle: tuple[Path, str]
) -> None:
    result, _model = _run(tmp_path, accepted_bundle, model=_Model(fail_call=7))
    ledger = json.loads((tmp_path / "attempt" / "provenance-ledger.private.json").read_bytes())

    assert result["status"] == "V25_BLIND_CVAT_QUEUE_READY"
    assert ledger["counts"]["inference_failed"] == 1
    assert ledger["counts"]["surviving"] == 279
    assert ledger["counts"]["selected"] > 0


def test_runner_public_bundle_and_zip_have_no_private_prediction_terms(
    tmp_path: Path, accepted_bundle: tuple[Path, str]
) -> None:
    _run(tmp_path, accepted_bundle)
    queue = tmp_path / "attempt" / "blind-queue"
    public = b"".join(
        path.read_bytes()
        for path in (queue / "cvat").rglob("*")
        if path.is_file()
    )
    with zipfile.ZipFile(queue / "cvat-upload.zip") as archive:
        public += b"".join(archive.read(name) for name in archive.namelist())
    for forbidden in (
        b"source_video",
        b"predictions",
        b"confidence",
        b"signals",
        b"bucket",
    ):
        assert forbidden not in public


def test_runner_cli_rejects_gate_and_protected_artifact_arguments() -> None:
    parser = runner.build_parser()
    for argument in (
        "--gate-root",
        "--validation153",
        "--internal-test151",
        "--owner-external60",
    ):
        with pytest.raises(SystemExit):
            parser.parse_args(
                [
                    "--bundle-dir", "/private/bundle",
                    "--expected-bundle-sha256", "1" * 64,
                    "--checkpoint", "/private/model.pt",
                    "--expected-checkpoint-sha256", "2" * 64,
                    "--freeze", "/private/freeze.json",
                    "--expected-freeze-sha256", "3" * 64,
                    "--output-root", "/private/output",
                    argument, "/forbidden",
                ]
            )


def test_runner_no_overwrite_rejects_existing_attempt_before_model_load(
    tmp_path: Path, accepted_bundle: tuple[Path, str]
) -> None:
    existing = tmp_path / "attempt"
    existing.mkdir()
    bundle, bundle_sha = accepted_bundle
    checkpoint, checkpoint_sha = _private_file(tmp_path / "best.pt", b"checkpoint")
    freeze, freeze_sha = _freeze(tmp_path, checkpoint_sha)
    with pytest.raises(FileExistsError):
        runner.run_minimal_owner_inference(
            bundle_dir=bundle,
            expected_bundle_sha256=bundle_sha,
            checkpoint=checkpoint,
            expected_checkpoint_sha256=checkpoint_sha,
            freeze=freeze,
            expected_freeze_sha256=freeze_sha,
            output_root=existing,
            model_factory=lambda _capability: (_ for _ in ()).throw(
                AssertionError("model must not load")
            ),
            runtime_probe=lambda: {},
        )


def test_runner_shortage_does_not_publish_ready_queue(
    tmp_path: Path, accepted_bundle: tuple[Path, str]
) -> None:
    class InvalidModel(_Model):
        def predict(self, **kwargs: object) -> list[object]:
            self.calls += 1
            return []

    result, _model = _run(tmp_path, accepted_bundle, model=InvalidModel())

    assert result["status"] == "V25_HARDCASE_QUEUE_SHORTAGE"
    assert not (tmp_path / "attempt" / "blind-queue").exists()
    assert not (tmp_path / "attempt" / "acceptance.private.json").exists()
