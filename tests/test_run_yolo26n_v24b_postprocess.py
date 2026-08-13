from __future__ import annotations

import hashlib
import json
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
    real_reserve = runner._reserve_private
    interleaved = False
    loads = 0

    def racing_reserve(path: Path) -> int:
        nonlocal interleaved
        if not interleaved:
            interleaved = True
            for winner_path, payload in winner_payloads.items():
                winner_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                winner_path.write_bytes(payload)
                winner_path.chmod(0o600)
        return real_reserve(path)

    def model_factory(_path: str):
        nonlocal loads
        loads += 1
        raise AssertionError("race loser must not load model")

    monkeypatch.setattr(runner, "_reserve_private", racing_reserve)
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


def test_prediction_ledgers_are_not_visible_while_their_json_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "attempt"
    real_publish = runner._publish_json_fd

    def observing_publish(fd: int, value: dict[str, object]) -> None:
        if value.get("schema") == "yolo26n-v24b-postprocess-prediction-ledger-v1":
            nms_iou = value["inference"]["nms_iou"]
            assert not (
                output
                / f"prediction-ledgers/nms-{round(nms_iou * 100):02d}.private.json"
            ).exists()
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
