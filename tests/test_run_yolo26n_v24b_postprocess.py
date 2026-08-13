from __future__ import annotations

import errno
import hashlib
import json
import platform
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

import scripts.run_yolo26n_v24b_postprocess as runner
from scripts.select_yolo26n_v24b_postprocess import NMS_GRID


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _png_payload(index: int) -> bytes:
    output = BytesIO()
    Image.new("RGB", (8, 6), (index % 251, (index * 7) % 251, 11)).save(
        output, format="PNG"
    )
    return output.getvalue()


def _dataset(tmp_path: Path, *, count: int = 153) -> tuple[Path, Path, list[Path]]:
    root = tmp_path / "dataset"
    records: list[dict[str, object]] = []
    images: list[Path] = []
    for index in range(count):
        sequence = f"V{index + 1:04d}"
        image_path = root / f"images/val/{sequence}.jpg"
        label_path = root / f"labels/val/{sequence}.txt"
        image_path.parent.mkdir(parents=True, exist_ok=True)
        label_path.parent.mkdir(parents=True, exist_ok=True)
        payload = _png_payload(index)
        image_path.write_bytes(payload)
        label_path.write_text("0 0.5 0.5 0.5 0.5\n", encoding="utf-8")
        images.append(image_path)
        records.append(
            {
                "sequence": sequence,
                "split": "val",
                "image_path": f"images/val/{sequence}.jpg",
                "label_path": f"labels/val/{sequence}.txt",
                "image_sha256": _sha(payload),
                "box_count": 1,
                "positive": True,
            }
        )
    manifest = root / "manifest.private.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "yolo26n-owner-dataset-v24",
                "evaluation_tier": "development",
                "future_holdout_required": True,
                "split_counts": {"train": 1458, "val": count, "test": 151},
                "records": records,
                "db_write_count": 0,
                "r2_write_count": 0,
                "service_write_count": 0,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return root, manifest, images


class _Tensor:
    def __init__(self, value):
        self.value = value

    def cpu(self):
        return self

    def tolist(self):
        return self.value


class _Boxes:
    def __init__(self):
        self.xyxy = _Tensor([[2.0, 1.5, 6.0, 4.5]])
        self.conf = _Tensor([0.90])


def _result(index: int):
    return type(
        "Result",
        (),
        {"path": f"image{index}.jpg", "orig_shape": (6, 8), "boxes": _Boxes()},
    )()


class _RecordingModel:
    def __init__(self, calls: list[dict[str, object]]):
        self.calls = calls

    def predict(self, *, source, **contract):
        self.calls.append({"source": source, **contract})
        return [_result(index) for index in range(len(source))]


def _run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    model_factory=None,
    output_name: str = "attempt",
):
    _, manifest, images = _dataset(tmp_path)
    checkpoint = tmp_path / "best.pt"
    checkpoint.write_bytes(b"verified-v24-checkpoint")
    checkpoint_sha = _sha(checkpoint.read_bytes())
    monkeypatch.setattr(runner, "V24_CHECKPOINT_SHA256", checkpoint_sha)
    calls: list[dict[str, object]] = []
    if model_factory is None:
        model_factory = lambda _path: _RecordingModel(calls)
    output = tmp_path / output_name
    result = runner.run_prediction_grid(
        dataset_manifest=manifest,
        expected_dataset_manifest_sha256=_sha(manifest.read_bytes()),
        checkpoint=checkpoint,
        expected_checkpoint_sha256=checkpoint_sha,
        output=output,
        source_commit="a" * 40,
        model_factory=model_factory,
    )
    return result, output, manifest, checkpoint, images, calls


def _ledger_paths(output: Path) -> list[Path]:
    return [
        output / f"prediction-ledgers/nms-{round(nms * 100):02d}.private.json"
        for nms in NMS_GRID
    ]


def _lock_paths(output: Path) -> list[Path]:
    return [
        output / f".locks/predict-nms-{round(nms * 100):02d}.started.private.json"
        for nms in NMS_GRID
    ]


def test_predict_grid_uses_exact_validation_contract_and_private_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loaded: list[tuple[Path, bytes, int]] = []
    calls: list[dict[str, object]] = []

    def model_factory(path: str):
        pinned = Path(path)
        loaded.append((pinned, pinned.read_bytes(), pinned.stat().st_mode & 0o777))
        return _RecordingModel(calls)

    result, output, manifest, checkpoint, images, _ = _run(
        tmp_path, monkeypatch, model_factory=model_factory
    )

    assert result == {
        "status": "V24B_POSTPROCESS_PREDICTIONS_READY",
        "image_count": 153,
        "ledger_count": 7,
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
        "git_write_count": 0,
    }
    assert loaded == [
        (
            output / ".pinned/v24-best.private.pt",
            b"verified-v24-checkpoint",
            0o600,
        )
    ]
    assert len(calls) == 7
    assert [call["iou"] for call in calls] == list(NMS_GRID)
    assert all(
        {
            "conf": call["conf"],
            "imgsz": call["imgsz"],
            "max_det": call["max_det"],
            "device": call["device"],
            "verbose": call["verbose"],
            "stream": call["stream"],
            "save": call["save"],
        }
        == {
            "conf": 0.001,
            "imgsz": 960,
            "max_det": 50,
            "device": "mps",
            "verbose": False,
            "stream": False,
            "save": False,
        }
        for call in calls
    )
    first_source = calls[0]["source"]
    assert all(
        [id(image) for image in call["source"]] == [id(image) for image in first_source]
        for call in calls
    )
    assert len(first_source) == 153

    ledger_paths = _ledger_paths(output)
    lock_paths = _lock_paths(output)
    assert all(path.is_file() and path.stat().st_mode & 0o777 == 0o600 for path in ledger_paths)
    assert all(path.is_file() and path.stat().st_mode & 0o777 == 0o600 for path in lock_paths)
    assert (output / ".pinned/v24-best.private.pt").stat().st_mode & 0o777 == 0o600
    ledger = json.loads(ledger_paths[0].read_text(encoding="utf-8"))
    assert ledger["schema"] == "yolo26n-v24b-postprocess-prediction-ledger-v1"
    assert ledger["status"] == "V24B_POSTPROCESS_PREDICTIONS_READY"
    assert ledger["dataset_manifest_sha256"] == _sha(manifest.read_bytes())
    assert ledger["checkpoint_sha256"] == _sha(checkpoint.read_bytes())
    assert ledger["input_sha256_pre"] == ledger["input_sha256_post"]
    assert ledger["records"][0] == {
        "sequence": "V0001",
        "image_sha256": _sha(images[0].read_bytes()),
        "label_sha256": _sha((tmp_path / "dataset/labels/val/V0001.txt").read_bytes()),
        "width": 8,
        "height": 6,
        "gt_boxes": [[2.0, 1.5, 6.0, 4.5]],
        "predictions": [{"confidence": 0.9, "xyxy": [2.0, 1.5, 6.0, 4.5]}],
    }
    assert ledger["db_write_count"] == ledger["r2_write_count"] == 0
    assert ledger["service_write_count"] == ledger["git_write_count"] == 0


@pytest.mark.parametrize("forbidden", ["test", "external"])
def test_predict_grid_rejects_test_or_external_path_before_model_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, forbidden: str
) -> None:
    _, manifest, _ = _dataset(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["records"][0]["image_path"] = f"images/{forbidden}/V0001.jpg"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    checkpoint = tmp_path / "best.pt"
    checkpoint.write_bytes(b"checkpoint")
    checkpoint_sha = _sha(checkpoint.read_bytes())
    monkeypatch.setattr(runner, "V24_CHECKPOINT_SHA256", checkpoint_sha)
    loads = 0

    def model_factory(_path: str):
        nonlocal loads
        loads += 1
        raise AssertionError("inference model must not load")

    with pytest.raises(ValueError, match="validation path"):
        runner.run_prediction_grid(
            dataset_manifest=manifest,
            expected_dataset_manifest_sha256=_sha(manifest.read_bytes()),
            checkpoint=checkpoint,
            expected_checkpoint_sha256=checkpoint_sha,
            output=tmp_path / "attempt",
            source_commit="a" * 40,
            model_factory=model_factory,
        )

    assert loads == 0
    assert not (tmp_path / "attempt").exists()


def test_predict_grid_rejects_non_153_manifest_and_wrong_exact_checkpoint_before_model_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, manifest, _ = _dataset(tmp_path, count=152)
    checkpoint = tmp_path / "best.pt"
    checkpoint.write_bytes(b"checkpoint")
    actual_sha = _sha(checkpoint.read_bytes())
    monkeypatch.setattr(runner, "V24_CHECKPOINT_SHA256", actual_sha)
    loads = 0

    def model_factory(_path: str):
        nonlocal loads
        loads += 1
        raise AssertionError("model must not load")

    with pytest.raises(ValueError, match="153"):
        runner.run_prediction_grid(
            dataset_manifest=manifest,
            expected_dataset_manifest_sha256=_sha(manifest.read_bytes()),
            checkpoint=checkpoint,
            expected_checkpoint_sha256=actual_sha,
            output=tmp_path / "count-attempt",
            source_commit="a" * 40,
            model_factory=model_factory,
        )
    with pytest.raises(ValueError, match="exact v2.4 checkpoint"):
        runner.run_prediction_grid(
            dataset_manifest=manifest,
            expected_dataset_manifest_sha256=_sha(manifest.read_bytes()),
            checkpoint=checkpoint,
            expected_checkpoint_sha256="0" * 64,
            output=tmp_path / "sha-attempt",
            source_commit="a" * 40,
            model_factory=model_factory,
        )
    assert loads == 0


@pytest.mark.parametrize("expected", ["A" * 64, "0" * 64])
def test_predict_grid_requires_independent_exact_dataset_manifest_pin_before_model_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, expected: str
) -> None:
    _, manifest, _ = _dataset(tmp_path)
    checkpoint = tmp_path / "best.pt"
    checkpoint.write_bytes(b"checkpoint")
    checkpoint_sha = _sha(checkpoint.read_bytes())
    monkeypatch.setattr(runner, "V24_CHECKPOINT_SHA256", checkpoint_sha)
    loads = 0

    def model_factory(_path: str):
        nonlocal loads
        loads += 1
        raise AssertionError("model must not load")

    with pytest.raises(ValueError, match="dataset manifest SHA"):
        runner.run_prediction_grid(
            dataset_manifest=manifest,
            expected_dataset_manifest_sha256=expected,
            checkpoint=checkpoint,
            expected_checkpoint_sha256=checkpoint_sha,
            output=tmp_path / "attempt",
            source_commit="a" * 40,
            model_factory=model_factory,
        )

    assert loads == 0
    assert not (tmp_path / "attempt").exists()


def test_predict_grid_accepts_approved_arbitrary_private_manifest_basename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, manifest, _ = _dataset(tmp_path)
    approved_manifest = manifest.with_name("dataset-manifest.private.json")
    manifest.rename(approved_manifest)
    checkpoint = tmp_path / "best.pt"
    checkpoint.write_bytes(b"checkpoint")
    checkpoint_sha = _sha(checkpoint.read_bytes())
    monkeypatch.setattr(runner, "V24_CHECKPOINT_SHA256", checkpoint_sha)
    calls: list[dict[str, object]] = []

    result = runner.run_prediction_grid(
        dataset_manifest=approved_manifest,
        expected_dataset_manifest_sha256=_sha(approved_manifest.read_bytes()),
        checkpoint=checkpoint,
        expected_checkpoint_sha256=checkpoint_sha,
        output=tmp_path / "attempt",
        source_commit="a" * 40,
        model_factory=lambda _path: _RecordingModel(calls),
    )

    assert result["ledger_count"] == 7
    assert len(calls) == 7


def test_predict_grid_cli_accepts_independent_dataset_manifest_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, manifest, _ = _dataset(tmp_path)
    checkpoint = tmp_path / "best.pt"
    checkpoint.write_bytes(b"checkpoint")
    checkpoint_sha = _sha(checkpoint.read_bytes())
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(runner, "V24_CHECKPOINT_SHA256", checkpoint_sha)
    monkeypatch.setattr(runner, "_source_commit", lambda: "a" * 40)
    monkeypatch.setattr(
        runner,
        "_make_model",
        lambda _checkpoint, _factory: _RecordingModel(calls),
    )

    exit_code = runner.main(
        [
            "predict-grid",
            "--dataset-manifest",
            str(manifest),
            "--expected-dataset-manifest-sha256",
            _sha(manifest.read_bytes()),
            "--checkpoint",
            str(checkpoint),
            "--expected-checkpoint-sha256",
            checkpoint_sha,
            "--output",
            str(tmp_path / "attempt"),
        ]
    )

    assert exit_code == 0
    assert len(calls) == 7


def test_verified_checkpoint_and_image_bytes_survive_aba_path_swaps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, manifest, images = _dataset(tmp_path)
    checkpoint = tmp_path / "best.pt"
    checkpoint_payload = b"checkpoint-before-aba"
    checkpoint.write_bytes(checkpoint_payload)
    checkpoint_sha = _sha(checkpoint_payload)
    monkeypatch.setattr(runner, "V24_CHECKPOINT_SHA256", checkpoint_sha)
    first_image_payload = images[0].read_bytes()
    seen: list[tuple[bytes, tuple[int, int, int]]] = []

    class AbaModel(_RecordingModel):
        def predict(self, *, source, **contract):
            if not seen:
                checkpoint.write_bytes(b"swapped-checkpoint")
                images[0].write_bytes(_png_payload(999))
                seen.append((Path(self.pinned).read_bytes(), source[0].getpixel((0, 0))))
                checkpoint.write_bytes(checkpoint_payload)
                images[0].write_bytes(first_image_payload)
            return super().predict(source=source, **contract)

    calls: list[dict[str, object]] = []

    def model_factory(pinned: str):
        model = AbaModel(calls)
        model.pinned = pinned
        return model

    runner.run_prediction_grid(
        dataset_manifest=manifest,
        expected_dataset_manifest_sha256=_sha(manifest.read_bytes()),
        checkpoint=checkpoint,
        expected_checkpoint_sha256=checkpoint_sha,
        output=tmp_path / "attempt",
        source_commit="a" * 40,
        model_factory=model_factory,
    )

    with Image.open(BytesIO(first_image_payload)) as expected_image:
        expected_pixel = expected_image.convert("RGB").getpixel((0, 0))
    assert seen == [(checkpoint_payload, expected_pixel)]


def test_reversed_ultralytics_result_order_fails_and_publishes_no_ledgers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class ReversedModel:
        def predict(self, *, source, **_contract):
            return list(reversed([_result(index) for index in range(len(source))]))

    with pytest.raises(ValueError, match="order"):
        _run(tmp_path, monkeypatch, model_factory=lambda _path: ReversedModel())

    output = tmp_path / "attempt"
    assert not any(path.exists() for path in _ledger_paths(output))
    assert all(path.exists() for path in _lock_paths(output))


def test_second_call_is_rejected_before_either_inference_can_duplicate_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, manifest, _ = _dataset(tmp_path)
    checkpoint = tmp_path / "best.pt"
    checkpoint.write_bytes(b"checkpoint")
    checkpoint_sha = _sha(checkpoint.read_bytes())
    monkeypatch.setattr(runner, "V24_CHECKPOINT_SHA256", checkpoint_sha)
    output = tmp_path / "attempt"
    nested_loads = 0

    class OuterModel(_RecordingModel):
        pass

    calls: list[dict[str, object]] = []

    def nested_factory(_path: str):
        nonlocal nested_loads
        nested_loads += 1
        raise AssertionError("second model must not load")

    def outer_factory(_path: str):
        with pytest.raises(FileExistsError):
            runner.run_prediction_grid(
                dataset_manifest=manifest,
                expected_dataset_manifest_sha256=_sha(manifest.read_bytes()),
                checkpoint=checkpoint,
                expected_checkpoint_sha256=checkpoint_sha,
                output=output,
                source_commit="a" * 40,
                model_factory=nested_factory,
            )
        return OuterModel(calls)

    runner.run_prediction_grid(
        dataset_manifest=manifest,
        expected_dataset_manifest_sha256=_sha(manifest.read_bytes()),
        checkpoint=checkpoint,
        expected_checkpoint_sha256=checkpoint_sha,
        output=output,
        source_commit="a" * 40,
        model_factory=outer_factory,
    )

    assert nested_loads == 0
    assert len(calls) == 7


def test_coordinator_race_loser_preserves_winner_owned_paths_and_never_loads_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, manifest, _ = _dataset(tmp_path)
    checkpoint = tmp_path / "best.pt"
    checkpoint.write_bytes(b"checkpoint")
    checkpoint_sha = _sha(checkpoint.read_bytes())
    monkeypatch.setattr(runner, "V24_CHECKPOINT_SHA256", checkpoint_sha)
    output = tmp_path / "attempt"
    coordinator = output / ".locks/predict-grid.started.private.json"
    winner_ledger = _ledger_paths(output)[0]
    winner_pinned = output / ".pinned/v24-best.private.pt"
    winner_payloads = {
        coordinator: b"winner-coordinator",
        winner_ledger: b"winner-ledger",
        winner_pinned: b"winner-pinned",
    }
    real_link = runner.os.link
    interleaved = False
    loads = 0

    def racing_link(source, destination, *args, **kwargs):
        nonlocal interleaved
        if not interleaved:
            interleaved = True
            for winner_path, payload in winner_payloads.items():
                winner_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                winner_path.write_bytes(payload)
                winner_path.chmod(0o600)
        return real_link(source, destination, *args, **kwargs)

    def model_factory(_path: str):
        nonlocal loads
        loads += 1
        raise AssertionError("race loser must not load model")

    monkeypatch.setattr(runner.os, "link", racing_link)
    with pytest.raises(FileExistsError):
        runner.run_prediction_grid(
            dataset_manifest=manifest,
            expected_dataset_manifest_sha256=_sha(manifest.read_bytes()),
            checkpoint=checkpoint,
            expected_checkpoint_sha256=checkpoint_sha,
            output=output,
            source_commit="a" * 40,
            model_factory=model_factory,
        )

    assert loads == 0
    assert {path: path.read_bytes() for path in winner_payloads} == winner_payloads


def test_locks_and_pinned_checkpoint_are_invisible_until_complete_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "attempt"
    checkpoint_payload = b"verified-v24-checkpoint"
    pinned = output / ".pinned/v24-best.private.pt"
    seen_lock_schemas: list[str] = []
    pinned_write_seen = False
    real_publish = runner._publish_json_fd
    real_write = runner.os.write

    def observing_publish(fd: int, value: dict[str, object]) -> None:
        schema = value.get("schema")
        target = None
        if schema == "yolo26n-v24b-postprocess-grid-started-lock-v1":
            target = output / ".locks/predict-grid.started.private.json"
        elif schema == "yolo26n-v24b-postprocess-started-lock-v1":
            target = output / f'.locks/{value["operation"]}.started.private.json'
        elif schema == "yolo26n-v24b-postprocess-freeze-started-lock-v1":
            target = output / ".locks/freeze.started.private.json"
        if target is not None:
            assert not target.exists()
            seen_lock_schemas.append(str(schema))
        real_publish(fd, value)

    def observing_write(fd: int, payload: bytes) -> int:
        nonlocal pinned_write_seen
        if payload == checkpoint_payload:
            assert not pinned.exists()
            pinned_write_seen = True
        return real_write(fd, payload)

    monkeypatch.setattr(runner, "_publish_json_fd", observing_publish)
    monkeypatch.setattr(runner.os, "write", observing_write)
    _run(tmp_path, monkeypatch)
    runner.freeze_prediction_grid(output=output)

    assert seen_lock_schemas.count(
        "yolo26n-v24b-postprocess-grid-started-lock-v1"
    ) == 1
    assert seen_lock_schemas.count("yolo26n-v24b-postprocess-started-lock-v1") == 7
    assert seen_lock_schemas.count(
        "yolo26n-v24b-postprocess-freeze-started-lock-v1"
    ) == 1
    assert pinned_write_seen
    assert pinned.read_bytes() == checkpoint_payload
    assert pinned.stat().st_mode & 0o777 == 0o600
    assert not list(output.rglob("*.tmp-*"))


@pytest.mark.parametrize(
    ("failure_schema", "target_relative"),
    [
        (
            "yolo26n-v24b-postprocess-grid-started-lock-v1",
            ".locks/predict-grid.started.private.json",
        ),
        (
            "yolo26n-v24b-postprocess-started-lock-v1",
            ".locks/predict-nms-40.started.private.json",
        ),
    ],
)
def test_lock_publish_failure_leaves_no_target_or_temporary_residue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_schema: str,
    target_relative: str,
) -> None:
    output = tmp_path / "attempt"
    real_publish = runner._publish_json_fd
    loads = 0

    def failing_publish(fd: int, value: dict[str, object]) -> None:
        if value.get("schema") == failure_schema:
            real_publish(fd, {"partial": True})
            raise OSError("injected lock publish failure")
        real_publish(fd, value)

    def model_factory(_path: str):
        nonlocal loads
        loads += 1
        raise AssertionError("lock failure must happen before model load")

    monkeypatch.setattr(runner, "_publish_json_fd", failing_publish)
    with pytest.raises(OSError, match="injected lock"):
        _run(tmp_path, monkeypatch, model_factory=model_factory)

    assert loads == 0
    assert not (output / target_relative).exists()
    assert not any(path.exists() for path in _ledger_paths(output))
    assert not list(output.rglob("*.tmp-*"))


def test_pinned_checkpoint_publish_failure_leaves_no_target_or_temporary_residue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "attempt"
    pinned = output / ".pinned/v24-best.private.pt"
    checkpoint_payload = b"verified-v24-checkpoint"
    real_write = runner.os.write
    loads = 0

    def failing_write(fd: int, payload: bytes) -> int:
        if payload == checkpoint_payload:
            real_write(fd, b"partial")
            raise OSError("injected pinned publish failure")
        return real_write(fd, payload)

    def model_factory(_path: str):
        nonlocal loads
        loads += 1
        raise AssertionError("pinned failure must happen before model load")

    monkeypatch.setattr(runner.os, "write", failing_write)
    with pytest.raises(OSError, match="injected pinned"):
        _run(tmp_path, monkeypatch, model_factory=model_factory)

    assert loads == 0
    assert not pinned.exists()
    assert not any(path.exists() for path in _ledger_paths(output))
    assert not list(output.rglob("*.tmp-*"))


def test_freeze_lock_publish_failure_leaves_no_target_or_temporary_residue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, output, _, _, _, _ = _run(tmp_path, monkeypatch)
    freeze_lock = output / ".locks/freeze.started.private.json"
    freeze_path = output / "v24b-postprocess-freeze.private.json"
    real_publish = runner._publish_json_fd

    def failing_publish(fd: int, value: dict[str, object]) -> None:
        if value.get("schema") == "yolo26n-v24b-postprocess-freeze-started-lock-v1":
            real_publish(fd, {"partial": True})
            raise OSError("injected freeze lock publish failure")
        real_publish(fd, value)

    monkeypatch.setattr(runner, "_publish_json_fd", failing_publish)
    with pytest.raises(OSError, match="injected freeze lock"):
        runner.freeze_prediction_grid(output=output)

    assert not freeze_lock.exists()
    assert not freeze_path.exists()
    assert not list(output.rglob("*.tmp-*"))


def test_preexisting_final_ledger_rejects_before_model_load_and_is_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, manifest, _ = _dataset(tmp_path)
    checkpoint = tmp_path / "best.pt"
    checkpoint.write_bytes(b"checkpoint")
    checkpoint_sha = _sha(checkpoint.read_bytes())
    monkeypatch.setattr(runner, "V24_CHECKPOINT_SHA256", checkpoint_sha)
    output = tmp_path / "attempt"
    preexisting = _ledger_paths(output)[3]
    preexisting.parent.mkdir(parents=True)
    preexisting.write_bytes(b"preexisting-final-owned-by-another-attempt")
    preexisting.chmod(0o600)
    loads = 0

    def model_factory(_path: str):
        nonlocal loads
        loads += 1
        raise AssertionError("preexisting final must reject before model load")

    with pytest.raises(FileExistsError):
        runner.run_prediction_grid(
            dataset_manifest=manifest,
            expected_dataset_manifest_sha256=_sha(manifest.read_bytes()),
            checkpoint=checkpoint,
            expected_checkpoint_sha256=checkpoint_sha,
            output=output,
            source_commit="a" * 40,
            model_factory=model_factory,
        )

    assert loads == 0
    assert preexisting.read_bytes() == b"preexisting-final-owned-by-another-attempt"


def test_all_final_ledger_paths_are_complete_private_reservations_during_inference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "attempt"
    calls: list[dict[str, object]] = []

    class InspectingModel(_RecordingModel):
        def predict(self, *, source, **contract):
            for expected_nms, path in zip(NMS_GRID, _ledger_paths(output), strict=True):
                reservation = json.loads(path.read_text(encoding="utf-8"))
                assert reservation["schema"] == (
                    "yolo26n-v24b-postprocess-ledger-reservation-v1"
                )
                assert reservation["status"] == "RESERVED"
                assert reservation["nms_iou"] == expected_nms
                assert len(reservation["owner_token"]) == 64
                assert path.stat().st_mode & 0o777 == 0o600
            return super().predict(source=source, **contract)

    _run(
        tmp_path,
        monkeypatch,
        model_factory=lambda _path: InspectingModel(calls),
    )

    assert len(calls) == 7
    assert all(
        json.loads(path.read_text(encoding="utf-8"))["schema"]
        == "yolo26n-v24b-postprocess-prediction-ledger-v1"
        for path in _ledger_paths(output)
    )


def test_reservation_inode_tamper_rejects_finalization_without_any_success_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "attempt"
    target = _ledger_paths(output)[0]
    tamper_payload = b'{"schema":"third-party","status":"TAMPERED"}\n'

    class TamperingModel(_RecordingModel):
        def predict(self, *, source, **contract):
            if not self.calls:
                assert all(path.is_file() for path in _ledger_paths(output))
                replacement = target.with_name(".attacker.private.json")
                replacement.write_bytes(tamper_payload)
                replacement.chmod(0o600)
                replacement.replace(target)
            return super().predict(source=source, **contract)

    calls: list[dict[str, object]] = []
    with pytest.raises(ValueError, match="reservation.*ownership"):
        _run(
            tmp_path,
            monkeypatch,
            model_factory=lambda _path: TamperingModel(calls),
        )

    assert target.read_bytes() == tamper_payload
    for path in _ledger_paths(output):
        if path.exists():
            assert json.loads(path.read_text(encoding="utf-8"))["schema"] != (
                "yolo26n-v24b-postprocess-prediction-ledger-v1"
            )
    assert not list(output.rglob("*.tmp-*"))


def test_finalize_failure_after_exchange_cleans_only_owned_ledger_and_no_partial_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "attempt"
    first_ledger = _ledger_paths(output)[0]
    real_exchange = runner._atomic_exchange_paths
    injected = False

    def failing_exchange(source: Path, destination: Path) -> None:
        nonlocal injected
        real_exchange(source, destination)
        if Path(destination) == first_ledger and not injected:
            injected = True
            raise OSError("injected post-exchange failure")

    monkeypatch.setattr(runner, "_atomic_exchange_paths", failing_exchange)
    with pytest.raises(OSError, match="post-exchange"):
        _run(tmp_path, monkeypatch)

    assert injected
    assert not any(path.exists() for path in _ledger_paths(output))
    assert not list(output.rglob("*.tmp-*"))


def test_attacker_swap_after_ownership_check_is_restored_without_successful_finalization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "attempt"
    target = _ledger_paths(output)[0]
    attacker_payload = b'{"schema":"third-party","status":"ATTACKER"}\n'
    real_owned = runner._artifact_is_self_owned
    target_checks = 0

    def swap_after_check(artifact) -> bool:
        nonlocal target_checks
        owned = real_owned(artifact)
        if artifact.path == target and owned:
            target_checks += 1
            # First call is the all-reservations preflight. The second is the
            # finalizer's last check immediately before its filesystem swap.
            if target_checks == 2:
                attacker = target.with_name(".attacker.private.json")
                attacker.write_bytes(attacker_payload)
                attacker.chmod(0o600)
                attacker.replace(target)
        return owned

    monkeypatch.setattr(runner, "_artifact_is_self_owned", swap_after_check)
    with pytest.raises(ValueError, match="reservation.*ownership"):
        _run(tmp_path, monkeypatch)

    assert target_checks >= 2
    assert target.read_bytes() == attacker_payload
    assert not any(
        json.loads(path.read_text(encoding="utf-8")).get("schema")
        == "yolo26n-v24b-postprocess-prediction-ledger-v1"
        for path in _ledger_paths(output)
        if path.exists()
    )
    assert not list(output.rglob("*.tmp-*"))


def test_atomic_exchange_failure_preserves_owned_reservation_and_cleans_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "nms-40.private.json"
    reservation_payload = {
        "schema": "yolo26n-v24b-postprocess-ledger-reservation-v1",
        "status": "RESERVED",
    }
    runner._atomic_write_private_json_new(path, reservation_payload)
    reservation = runner._capture_owned_artifact(path)

    monkeypatch.setattr(
        runner,
        "_atomic_exchange_paths",
        lambda _left, _right: (_ for _ in ()).throw(OSError("exchange failed")),
    )
    with pytest.raises(OSError, match="exchange failed"):
        runner._atomic_replace_owned_json(
            reservation,
            {"schema": "yolo26n-v24b-postprocess-prediction-ledger-v1"},
        )

    assert runner._capture_owned_artifact(path) == reservation
    assert json.loads(path.read_text(encoding="utf-8")) == reservation_payload
    assert not list(tmp_path.glob("*.tmp-*"))


@pytest.mark.parametrize(
    ("artifact_name", "payload_kind"),
    [
        (".locks/predict-grid.started.private.json", "json"),
        (".locks/predict-nms-40.started.private.json", "json"),
        (".locks/freeze.started.private.json", "json"),
        (".pinned/v24-best.private.pt", "bytes"),
    ],
)
def test_private_publishers_return_exact_owned_artifact(
    tmp_path: Path, artifact_name: str, payload_kind: str
) -> None:
    path = tmp_path / artifact_name
    if payload_kind == "json":
        value = {"schema": "private-test-v1", "status": "COMPLETE"}
        owned = runner._write_private_new(path, value)
        expected = (
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode()
    else:
        expected = b"exact-pinned-checkpoint"
        owned = runner._write_private_bytes_new(path, expected)

    assert owned == runner._capture_owned_artifact(path)
    assert owned.size == len(expected)
    assert path.read_bytes() == expected
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    ("artifact_name", "payload_kind"),
    [
        (".locks/predict-grid.started.private.json", "json"),
        (".locks/predict-nms-40.started.private.json", "json"),
        (".locks/freeze.started.private.json", "json"),
        (".pinned/v24-best.private.pt", "bytes"),
    ],
)
def test_post_link_third_party_replacement_survives_directory_fsync_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    artifact_name: str,
    payload_kind: str,
) -> None:
    path = tmp_path / artifact_name
    attacker_payload = b"third-party-replacement"
    real_link = runner.os.link
    real_fsync_directory = runner._fsync_directory
    published_path: Path | None = None

    def observing_link(source, destination, *args, **kwargs):
        nonlocal published_path
        result = real_link(source, destination, *args, **kwargs)
        published_path = Path(destination)
        return result

    def failing_directory_fsync(directory: Path) -> None:
        if published_path == path:
            attacker = path.with_name(".third-party.private")
            attacker.write_bytes(attacker_payload)
            attacker.chmod(0o600)
            attacker.replace(path)
            raise OSError("injected directory fsync failure")
        real_fsync_directory(directory)

    monkeypatch.setattr(runner.os, "link", observing_link)
    monkeypatch.setattr(runner, "_fsync_directory", failing_directory_fsync)
    with pytest.raises(OSError, match="directory fsync"):
        if payload_kind == "json":
            runner._write_private_new(path, {"schema": "private-test-v1"})
        else:
            runner._write_private_bytes_new(path, b"checkpoint")

    assert path.read_bytes() == attacker_payload
    assert not list(path.parent.glob("*.tmp-*"))


@pytest.mark.parametrize(
    "target_kind", ["coordinator", "nms-lock", "pinned"]
)
def test_pre_inference_cleanup_preserves_replaced_artifact_and_removes_only_owned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target_kind: str,
) -> None:
    output = tmp_path / "attempt"
    target = {
        "coordinator": output / ".locks/predict-grid.started.private.json",
        "nms-lock": _lock_paths(output)[0],
        "pinned": output / ".pinned/v24-best.private.pt",
    }[target_kind]
    attacker_payload = f"third-party-{target_kind}".encode()

    def failing_factory(_path: str):
        attacker = target.with_name(f".attacker-{target_kind}.private")
        attacker.write_bytes(attacker_payload)
        attacker.chmod(0o600)
        attacker.replace(target)
        raise RuntimeError("injected pre-inference failure")

    with pytest.raises(RuntimeError, match="pre-inference"):
        _run(tmp_path, monkeypatch, model_factory=failing_factory)

    assert target.read_bytes() == attacker_payload
    assert not any(
        path.exists() for path in _ledger_paths(output)
    )
    for path in [
        output / ".locks/predict-grid.started.private.json",
        *_lock_paths(output),
        output / ".pinned/v24-best.private.pt",
    ]:
        if path != target:
            assert not path.exists()
    assert not list(output.rglob("*.tmp-*"))


def test_cleanup_never_unlinks_contested_target_after_ownership_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "contested.private.json"
    target.write_bytes(b"self-owned")
    target.chmod(0o600)
    owned = runner._capture_owned_artifact(target)
    attacker = tmp_path / ".attacker.private.json"
    attacker.write_bytes(b"third-party")
    attacker.chmod(0o600)
    attacker_inode = attacker.stat().st_ino
    real_exchange = runner._atomic_exchange_paths
    real_unlink = Path.unlink
    swapped = False
    contested_unlinks = 0

    def swap_before_quarantine_exchange(left: Path, right: Path) -> None:
        nonlocal swapped
        if target in {left, right} and not swapped:
            swapped = True
            attacker.replace(target)
        real_exchange(left, right)

    def forbid_contested_unlink(path: Path, *args, **kwargs):
        nonlocal contested_unlinks
        if path == target:
            contested_unlinks += 1
            raise AssertionError("contested target unlink is forbidden")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(runner, "_atomic_exchange_paths", swap_before_quarantine_exchange)
    monkeypatch.setattr(Path, "unlink", forbid_contested_unlink)
    assert runner._cleanup_if_self_owned(owned) is False

    assert swapped
    assert contested_unlinks == 0
    assert any(
        path.stat().st_ino == attacker_inode for path in tmp_path.rglob("*") if path.is_file()
    )


def test_rollback_failure_preserves_displaced_attacker_in_private_quarantine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "nms-40.private.json"
    runner._atomic_write_private_json_new(
        target,
        {
            "schema": "yolo26n-v24b-postprocess-ledger-reservation-v1",
            "status": "RESERVED",
        },
    )
    reservation = runner._capture_owned_artifact(target)
    attacker = tmp_path / ".attacker.private.json"
    attacker.write_bytes(b"third-party-displaced")
    attacker.chmod(0o600)
    attacker_inode = attacker.stat().st_ino
    real_owned = runner._artifact_is_self_owned
    real_exchange = runner._atomic_exchange_paths
    target_checks = exchange_count = 0

    def swap_after_check(artifact) -> bool:
        nonlocal target_checks
        result = real_owned(artifact)
        if artifact.path == target and result:
            target_checks += 1
            if target_checks == 1:
                attacker.replace(target)
        return result

    def fail_rollback(left: Path, right: Path) -> None:
        nonlocal exchange_count
        exchange_count += 1
        if exchange_count == 2:
            raise OSError("injected rollback failure")
        real_exchange(left, right)

    monkeypatch.setattr(runner, "_artifact_is_self_owned", swap_after_check)
    monkeypatch.setattr(runner, "_atomic_exchange_paths", fail_rollback)
    with pytest.raises(OSError, match="rollback failure"):
        runner._atomic_replace_owned_json(
            reservation,
            {"schema": "yolo26n-v24b-postprocess-prediction-ledger-v1"},
        )

    attacker_paths = [
        path
        for path in tmp_path.rglob("*")
        if path.is_file() and path.stat().st_ino == attacker_inode
    ]
    assert exchange_count >= 2
    assert len(attacker_paths) == 1
    assert ".quarantine-" in str(attacker_paths[0])
    assert attacker_paths[0].read_bytes() == b"third-party-displaced"
    assert attacker_paths[0].stat().st_mode & 0o777 == 0o600
    assert attacker_paths[0].parent.stat().st_mode & 0o777 == 0o700


def test_quarantine_entry_replacement_after_capture_is_never_unlinked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "owned.private.json"
    target.write_bytes(b"owned")
    target.chmod(0o600)
    owned = runner._capture_owned_artifact(target)
    attacker_inode: int | None = None
    quarantine_observed = False
    quarantine_unlinks = 0
    real_capture = runner._capture_owned_artifact
    real_unlink = Path.unlink

    def replace_after_quarantine_capture(path: Path):
        nonlocal attacker_inode, quarantine_observed
        captured = real_capture(path)
        if ".quarantine-" in str(path) and not quarantine_observed:
            quarantine_observed = True
            attacker = path.with_name(".quarantine-attacker.private")
            attacker.write_bytes(b"quarantine-third-party")
            attacker.chmod(0o600)
            attacker_inode = attacker.stat().st_ino
            attacker.replace(path)
        return captured

    def forbid_quarantine_unlink(path: Path, *args, **kwargs):
        nonlocal quarantine_unlinks
        if ".quarantine-" in str(path):
            quarantine_unlinks += 1
            raise AssertionError("quarantine entries must never be unlinked")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(runner, "_capture_owned_artifact", replace_after_quarantine_capture)
    monkeypatch.setattr(Path, "unlink", forbid_quarantine_unlink)
    with pytest.raises(ValueError, match="ownership"):
        runner._cleanup_if_self_owned(owned)

    assert quarantine_observed
    assert quarantine_unlinks == 0
    assert attacker_inode is not None
    assert any(
        path.stat().st_ino == attacker_inode for path in tmp_path.rglob("*") if path.is_file()
    )


def test_real_filesystem_cross_directory_atomic_exchange_or_fail_closed(
    tmp_path: Path,
) -> None:
    left_dir = tmp_path / "left"
    right_dir = tmp_path / "right"
    left_dir.mkdir()
    right_dir.mkdir()
    left = left_dir / "left.private"
    right = right_dir / "right.private"
    left.write_bytes(b"left")
    right.write_bytes(b"right")
    left.chmod(0o600)
    right.chmod(0o600)
    left_inode = left.stat().st_ino
    right_inode = right.stat().st_ino

    if platform.system() in {"Darwin", "Linux"}:
        runner._atomic_exchange_paths(left, right)
        assert (left.read_bytes(), left.stat().st_ino) == (b"right", right_inode)
        assert (right.read_bytes(), right.stat().st_ino) == (b"left", left_inode)
    else:
        with pytest.raises(OSError) as caught:
            runner._atomic_exchange_paths(left, right)
        assert caught.value.errno == errno.ENOTSUP
        assert (left.read_bytes(), right.read_bytes()) == (b"left", b"right")


def test_publish_failure_removes_every_prediction_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_publish = runner._publish_json_fd
    publish_count = 0

    def failing_publish(fd: int, value: dict[str, object]) -> None:
        nonlocal publish_count
        if value.get("schema") == "yolo26n-v24b-postprocess-prediction-ledger-v1":
            publish_count += 1
            if publish_count == 2:
                raise OSError("injected publish failure")
        real_publish(fd, value)

    monkeypatch.setattr(runner, "_publish_json_fd", failing_publish)

    with pytest.raises(OSError, match="injected"):
        _run(tmp_path, monkeypatch)

    output = tmp_path / "attempt"
    assert not any(path.exists() for path in _ledger_paths(output))
    assert all(path.exists() and path.stat().st_mode & 0o777 == 0o600 for path in _lock_paths(output))
    assert not list(output.rglob("*.tmp-*"))


def test_prediction_ledgers_show_only_complete_reservations_while_final_json_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "attempt"
    real_publish = runner._publish_json_fd

    def observing_publish(fd: int, value: dict[str, object]) -> None:
        if value.get("schema") == "yolo26n-v24b-postprocess-prediction-ledger-v1":
            nms_iou = value["inference"]["nms_iou"]
            visible = json.loads((
                output
                / f"prediction-ledgers/nms-{round(nms_iou * 100):02d}.private.json"
            ).read_text(encoding="utf-8"))
            assert visible["schema"] == "yolo26n-v24b-postprocess-ledger-reservation-v1"
            assert visible["status"] == "RESERVED"
        real_publish(fd, value)

    monkeypatch.setattr(runner, "_publish_json_fd", observing_publish)
    _run(tmp_path, monkeypatch)

    assert all(path.is_file() for path in _ledger_paths(output))
    assert not list(output.rglob("*.tmp-*"))


def test_freeze_requires_all_verified_ledgers_then_writes_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, output, _, _, _, _ = _run(tmp_path, monkeypatch)

    freeze = runner.freeze_prediction_grid(output=output)

    freeze_path = output / "v24b-postprocess-freeze.private.json"
    freeze_lock = output / ".locks/freeze.started.private.json"
    assert freeze["status"] == "V24B_POSTPROCESS_FROZEN_DEVELOPMENT_ONLY"
    assert freeze["selected"] == {
        "confidence": 0.8,
        "nms_iou": 0.4,
        "duplicate": 0,
    }
    assert freeze["selector_sha256"] == _sha(
        Path(runner.selector.__file__).read_bytes()
    )
    assert freeze["db_write_count"] == freeze["r2_write_count"] == 0
    assert freeze["service_write_count"] == freeze["git_write_count"] == 0
    assert freeze_path.stat().st_mode & 0o777 == 0o600
    assert freeze_lock.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        runner.freeze_prediction_grid(output=output)


def test_freeze_is_not_visible_while_its_json_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, output, _, _, _, _ = _run(tmp_path, monkeypatch)
    freeze_path = output / "v24b-postprocess-freeze.private.json"
    real_publish = runner._publish_json_fd

    def observing_publish(fd: int, value: dict[str, object]) -> None:
        if value.get("schema") == "yolo26n-v24b-postprocess-freeze-v1":
            assert not freeze_path.exists()
        real_publish(fd, value)

    monkeypatch.setattr(runner, "_publish_json_fd", observing_publish)
    runner.freeze_prediction_grid(output=output)

    assert freeze_path.is_file()
    assert not list(output.rglob("*.tmp-*"))


def test_freeze_publish_failure_leaves_no_final_or_temporary_residue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, output, _, _, _, _ = _run(tmp_path, monkeypatch)
    freeze_path = output / "v24b-postprocess-freeze.private.json"
    freeze_lock = output / ".locks/freeze.started.private.json"
    real_publish = runner._publish_json_fd

    def failing_publish(fd: int, value: dict[str, object]) -> None:
        if value.get("schema") == "yolo26n-v24b-postprocess-freeze-v1":
            real_publish(fd, {"partial": True})
            raise OSError("injected freeze publish failure")
        real_publish(fd, value)

    monkeypatch.setattr(runner, "_publish_json_fd", failing_publish)
    with pytest.raises(OSError, match="injected freeze"):
        runner.freeze_prediction_grid(output=output)

    assert not freeze_path.exists()
    assert freeze_lock.is_file() and freeze_lock.stat().st_mode & 0o777 == 0o600
    assert not list(output.rglob("*.tmp-*"))


def test_freeze_rejects_missing_or_tampered_ledger_without_partial_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, output, _, _, _, _ = _run(tmp_path, monkeypatch)
    _ledger_paths(output)[-1].unlink()

    with pytest.raises(FileNotFoundError):
        runner.freeze_prediction_grid(output=output)

    assert not (output / "v24b-postprocess-freeze.private.json").exists()
    assert not (output / ".locks/freeze.started.private.json").exists()

    _, second, _, _, _, _ = _run(
        tmp_path / "other", monkeypatch, output_name="attempt"
    )
    ledger_path = _ledger_paths(second)[0]
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["input_sha256_post"]["checkpoint"] = "0" * 64
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    with pytest.raises(ValueError, match="provenance"):
        runner.freeze_prediction_grid(output=second)
    assert not (second / "v24b-postprocess-freeze.private.json").exists()
    assert not (second / ".locks/freeze.started.private.json").exists()
