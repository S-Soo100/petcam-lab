"""GME v2.6 을 production 계약 그대로 로컬(MacBook, gate venv)에서 돌려 확장 artifact 를 남기는 연구 러너.

실행 (gate venv 의 python 으로 — gecko_vision_gate·ultralytics·torch 가 거기 있다):
  nice -n 10 <gate>/.venv/bin/python scripts/nonvlm_behavior_v0/run_gme_local.py \
      --manifest /Users/baek/petcam-lab/storage/dataset-203/manifest.csv \
      --clips-dir /Users/baek/petcam-lab/storage/dataset-203 \
      --out-dir   /Users/baek/petcam-lab/storage/nonvlm-behavior-v0/gme \
      --run-id    smoke-3 --limit 3

DB·R2 write 0. 실패 artifact 는 재시도 대상(should_skip 이 status=ok 만 skip).
gate 패키지는 main() 안에서만 import 한다 → 순수 함수는 petcam-lab venv 에서 테스트 가능.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import sys
import time
from pathlib import Path

CONTRACT = {
    # nightly reporter/config.py 기본값 == install-launchd-gme.sh 강제값 (2026-09-09 실독)
    "detector_backend": "yolo26n",
    "model_version": "v2.6-warm-start-s28",
    "checkpoint_path": "/Users/baek/private-rba/yolo26n-v26-recent-dense/attempt-20260826-owner-v1/runs-v26-comparison-v2/warm-start-s28/weights/best.pt",
    "checkpoint_sha256": "a00e5a7a1e1f9197accb036339a38a7c821f03c8ab79611ebce89e5cde59b513",
    "detector_freeze_sha256": "8f8e02beb452ec2ddfdce344dff507294f56136c69224990c50552d22bb343a0",
    "detector_identity": "deccfc8315d3c00edb5bf59db3c573dca568e9d6d7a5da8d7dc93d2082bdb899",
    "raw_confidence": 0.001,
    "score_threshold": 0.15,
    "image_size": 960,
    "nms_iou": 0.70,
    "post_nms_iou": 0.55,
    "max_detections": 50,
    "analysis_fps": 10.0,
    "anchor_interval_sec": 0.1,
    "temporal_window_frames": 5,
    "temporal_min_positive_frames": 3,
    "algorithm_version": "gme-motion-v1",
    "engine_schema_version": "gme-shadow-v1",
    "device": "mps",
}

SUMMARY_FIELDS = (
    "status", "duration_sec", "decoded_frame_count", "analyzed_frame_count", "source_fps",
    "candidate_moving_sec_any_gecko", "moving_gecko_seconds", "visible_sec", "unknown_sec",
    "camera_motion_sec", "max_simultaneous_geckos",
)


class ContractMismatch(RuntimeError):
    """production GME 계약과 하나라도 다르면 run 무효 (시험지 §3)."""


def assert_contract(*, detector_identity: str, algorithm_version: str, engine_config_v26: bool) -> None:
    if detector_identity != CONTRACT["detector_identity"]:
        raise ContractMismatch(f"detector_identity mismatch: {detector_identity[:12]}…")
    if algorithm_version != CONTRACT["algorithm_version"]:
        raise ContractMismatch(f"algorithm_version mismatch: {algorithm_version}")
    if not engine_config_v26:
        raise ContractMismatch("engine_config is not GMEConfig.v26()")


def build_extended_artifact(*, analysis, permanent_gzip: bytes, filename: str, source_sha256: str,
                            elapsed_sec: float, run_id: str) -> dict:
    return {
        "gme": json.loads(gzip.decompress(permanent_gzip)),
        "summary": {name: getattr(analysis, name) for name in SUMMARY_FIELDS},
        "frame_debug": list(analysis.frame_debug),
        "source": {"filename": filename, "sha256": source_sha256},
        "run": {"run_id": run_id, "elapsed_sec": elapsed_sec, "contract": dict(CONTRACT)},
    }


def should_skip(out_path: Path) -> bool:
    if not out_path.exists():
        return False
    try:
        doc = json.loads(gzip.decompress(out_path.read_bytes()))
    except (OSError, ValueError):
        return False
    return doc.get("summary", {}).get("status") == "ok"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_git_head(repo_dir: Path) -> str:
    """git 명령 없이 파일만 읽어 HEAD commit 을 구한다 (worktree 의 `.git` 파일도 처리). 실패 시 'unknown'."""
    try:
        dot_git = repo_dir / ".git"
        gitdir = Path(dot_git.read_text().split("gitdir:", 1)[1].strip()) if dot_git.is_file() else dot_git
        head = (gitdir / "HEAD").read_text().strip()
        if not head.startswith("ref:"):
            return head
        ref = head.split("ref:", 1)[1].strip()
        common = gitdir / (gitdir / "commondir").read_text().strip() if (gitdir / "commondir").exists() else gitdir
        ref_path = (common / ref).resolve()
        if ref_path.exists():
            return ref_path.read_text().strip()
        packed = common / "packed-refs"
        for line in packed.read_text().splitlines() if packed.exists() else []:
            parts = line.split()
            if len(parts) == 2 and parts[1] == ref:
                return parts[0]
    except OSError:
        pass
    return "unknown"


def _write_json(path: Path, doc: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True))
    tmp.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--clips-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--limit", type=int, default=0, help="앞에서 N건만 (smoke). 0=전체")
    args = parser.parse_args(argv)

    # gate 패키지는 여기서만 (gate venv 전용)
    import gecko_vision_gate
    from gecko_vision_gate.gme_contracts import GMEConfig
    from gecko_vision_gate.gme_engine import ALGORITHM_VERSION, ENGINE_SCHEMA_VERSION, analyze_clip, detector_identity
    from gecko_vision_gate.gme_serialization import serialize_artifacts
    from gecko_vision_gate.gme_yolo_detector import build_yolo_detector

    detector = build_yolo_detector(
        checkpoint=CONTRACT["checkpoint_path"],
        expected_sha256=CONTRACT["checkpoint_sha256"],
        model_version=CONTRACT["model_version"],
        raw_confidence=CONTRACT["raw_confidence"],
        score_threshold=CONTRACT["score_threshold"],
        image_size=CONTRACT["image_size"],
        nms_iou=CONTRACT["nms_iou"],
        post_nms_iou=CONTRACT["post_nms_iou"],
        max_detections=CONTRACT["max_detections"],
        analysis_fps=CONTRACT["analysis_fps"],
        temporal_window_frames=CONTRACT["temporal_window_frames"],
        temporal_min_positive_frames=CONTRACT["temporal_min_positive_frames"],
        device=CONTRACT["device"],
    )
    identity = detector_identity(detector)
    config = GMEConfig.v26()
    assert_contract(detector_identity=identity, algorithm_version=ALGORITHM_VERSION, engine_config_v26=config == GMEConfig.v26())
    if ENGINE_SCHEMA_VERSION != CONTRACT["engine_schema_version"]:
        raise ContractMismatch(f"engine_schema_version mismatch: {ENGINE_SCHEMA_VERSION}")

    gate_dir = Path(gecko_vision_gate.__file__).resolve().parents[2]
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    clips_dir = Path(args.clips_dir)
    with open(args.manifest, newline="") as fh:
        rows = sorted(csv.DictReader(fh), key=lambda r: r["filename"])  # 결정론 순서, GT 컬럼은 읽지 않음
    if args.limit:
        rows = rows[: args.limit]

    import torch, ultralytics  # noqa: E401 — 버전 박제용

    records = []
    started = time.time()
    for i, row in enumerate(rows, 1):
        filename = row["filename"]
        out_path = out_dir / f"{filename}.json.gz"
        if should_skip(out_path):
            records.append({"filename": filename, "status": "skipped_existing"})
            continue
        clip = clips_dir / filename
        t0 = time.time()
        try:
            analysis = analyze_clip(clip, detector=detector, config=config)
        except (RuntimeError, ValueError, OSError) as exc:  # torch/cv2 런타임 오류만; 기록 후 다음 클립
            elapsed = time.time() - t0
            print(f"[{i}/{len(rows)}] {filename} EXC {type(exc).__name__}: {exc}", file=sys.stderr)
            records.append({"filename": filename, "status": f"exception:{type(exc).__name__}", "elapsed_sec": elapsed})
            continue
        elapsed = time.time() - t0
        serialized = serialize_artifacts(analysis)
        doc = build_extended_artifact(
            analysis=analysis, permanent_gzip=serialized.permanent_gzip, filename=filename,
            source_sha256=_sha256(clip), elapsed_sec=elapsed, run_id=args.run_id,
        )
        tmp = out_path.with_suffix(".part")
        tmp.write_bytes(gzip.compress(json.dumps(doc, ensure_ascii=False, sort_keys=True).encode(), mtime=0))
        tmp.replace(out_path)
        records.append({
            "filename": filename, "status": analysis.status, "elapsed_sec": round(elapsed, 3),
            "duration_sec": analysis.duration_sec, "analyzed_frames": analysis.analyzed_frame_count,
            "permanent_sha256": serialized.permanent_sha256,
        })
        print(f"[{i}/{len(rows)}] {filename} {analysis.status} {elapsed:.1f}s "
              f"moving={analysis.candidate_moving_sec_any_gecko:.1f}s visible={analysis.visible_sec:.1f}s", flush=True)

    manifest = {
        "run_id": args.run_id,
        "contract": CONTRACT,
        "verified": {"detector_identity": identity, "algorithm_version": ALGORITHM_VERSION,
                     "engine_schema_version": ENGINE_SCHEMA_VERSION, "engine_config": config.__dict__ if hasattr(config, "__dict__") else str(config)},
        "gate_package": str(gate_dir), "gate_head": _read_git_head(gate_dir),
        "versions": {"ultralytics": ultralytics.__version__, "torch": torch.__version__, "python": sys.version.split()[0]},
        "clips_dir": str(clips_dir), "manifest": args.manifest, "limit": args.limit,
        "started_at_epoch": started, "total_elapsed_sec": round(time.time() - started, 1),
        "records": records,
        "counts": {s: sum(1 for r in records if r["status"] == s) for s in sorted({r["status"] for r in records})},
    }
    _write_json(out_dir / f"run-manifest.{args.run_id}.json", manifest)
    print(json.dumps(manifest["counts"]), f"total {manifest['total_elapsed_sec']}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
