"""Formal Blind30 immutable raw-submission scorer and JSON-only CLI."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Literal, Mapping, Sequence

SCORER_VERSION = "rba-blind30-scorer-v1"
_ABSTAINS = {"uncertain", "unjudgeable"}
_REVIEWER_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{12,64}$")
_AUDIT_VIOLATION_FIELDS = (
    "blind_exposure",
    "sample_replacement",
    "reviewer_qualification_violation",
    "historical_sample_reuse",
)
_AUDIT_SYSTEM_FIELD = "media_or_system_issue"


class Blind30ScoringError(ValueError):
    """Raw export or manifest does not satisfy the frozen scorer contract."""


def _number(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise Blind30ScoringError(f"invalid_{field}")
    return float(value)


def _normalized_segment(segment: Mapping[str, object]) -> tuple[str, float, float]:
    action = segment.get("action")
    if not isinstance(action, str) or not action:
        raise Blind30ScoringError("invalid_segment_action")
    start = _number(segment.get("start_sec"), field="segment_start")
    end = _number(segment.get("end_sec"), field="segment_end")
    if start < 0 or end < start:
        raise Blind30ScoringError("invalid_segment_range")
    return action, start, end


def _segments_match(
    left: tuple[str, float, float],
    right: tuple[str, float, float],
) -> bool:
    if left[0] != right[0]:
        return False
    overlap = max(0.0, min(left[2], right[2]) - max(left[1], right[1]))
    union = max(left[2], right[2]) - min(left[1], right[1])
    iou = overlap / union if union > 0 else float(left[1:] == right[1:])
    boundary_match = (
        abs(left[1] - right[1]) <= 2.0 and abs(left[2] - right[2]) <= 2.0
    )
    return iou >= 0.50 or boundary_match


def match_segments(
    reviewer_a: Sequence[Mapping[str, object]],
    reviewer_b: Sequence[Mapping[str, object]],
) -> dict[str, int]:
    """Maximum-cardinality bipartite match under the frozen action/time edge rule."""

    left = sorted(_normalized_segment(row) for row in reviewer_a)
    right = sorted(_normalized_segment(row) for row in reviewer_b)
    edges = [
        [index for index, candidate in enumerate(right) if _segments_match(row, candidate)]
        for row in left
    ]
    right_match: dict[int, int] = {}

    def augment(left_index: int, seen: set[int]) -> bool:
        for right_index in edges[left_index]:
            if right_index in seen:
                continue
            seen.add(right_index)
            previous = right_match.get(right_index)
            if previous is None or augment(previous, seen):
                right_match[right_index] = left_index
                return True
        return False

    matched = sum(augment(index, set()) for index in range(len(left)))
    return {
        "tp": matched,
        "fp": len(left) - matched,
        "fn": len(right) - matched,
    }


def _index_submissions(
    rows: Sequence[Mapping[str, object]],
) -> tuple[dict[str, Mapping[str, object]], int]:
    indexed: dict[str, Mapping[str, object]] = {}
    duplicates = 0
    for row in rows:
        clip_id = row.get("clip_id")
        if not isinstance(clip_id, str) or not clip_id:
            raise Blind30ScoringError("invalid_clip_id")
        if clip_id in indexed:
            duplicates += 1
        else:
            indexed[clip_id] = row
    return indexed, duplicates


def _reviewer_fingerprint(rows: Sequence[Mapping[str, object]]) -> str:
    values = {row.get("reviewer_fingerprint") for row in rows}
    if len(values) != 1:
        raise Blind30ScoringError("inconsistent_reviewer_fingerprint")
    value = next(iter(values), None)
    if (
        not isinstance(value, str)
        or _REVIEWER_FINGERPRINT_RE.fullmatch(value) is None
    ):
        raise Blind30ScoringError("invalid_reviewer_fingerprint")
    return value


def _contract_audit(
    audit: Mapping[str, object] | None,
) -> tuple[bool, int, bool]:
    if audit is None:
        return False, 0, False
    required = {*_AUDIT_VIOLATION_FIELDS, _AUDIT_SYSTEM_FIELD}
    if set(audit) != required or any(
        not isinstance(audit[field], bool) for field in required
    ):
        raise Blind30ScoringError("invalid_contract_audit")
    violations = sum(bool(audit[field]) for field in _AUDIT_VIOLATION_FIELDS)
    return True, violations, bool(audit[_AUDIT_SYSTEM_FIELD])


def _confidence(row: Mapping[str, object]) -> object:
    direct = row.get("confidence")
    if direct is not None:
        return direct
    gt = row.get("initial_gt")
    return gt.get("human_confidence") if isinstance(gt, Mapping) else None


def _abstains(row: Mapping[str, object]) -> bool:
    return _confidence(row) in _ABSTAINS


def _gt(row: Mapping[str, object]) -> Mapping[str, object] | None:
    value = row.get("initial_gt")
    return value if isinstance(value, Mapping) else None


def _dimension() -> dict[str, object]:
    return {"agreements": 0, "evaluable": 0, "rate": None}


def _finalize_dimension(metric: dict[str, object]) -> None:
    evaluable = int(metric["evaluable"])
    metric["rate"] = (
        round(int(metric["agreements"]) / evaluable, 6) if evaluable else None
    )


def _as_string_set(value: object, *, field: str) -> frozenset[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise Blind30ScoringError(f"invalid_{field}")
    return frozenset(value)


def score_blind30(
    reviewer_a: Sequence[Mapping[str, object]],
    reviewer_b: Sequence[Mapping[str, object]],
    *,
    audit: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Score paired immutable submissions without consulting consensus or final rows."""

    indexed_a, duplicate_a = _index_submissions(reviewer_a)
    indexed_b, duplicate_b = _index_submissions(reviewer_b)
    fingerprint_a = _reviewer_fingerprint(reviewer_a)
    fingerprint_b = _reviewer_fingerprint(reviewer_b)
    if fingerprint_a == fingerprint_b:
        raise Blind30ScoringError("distinct_reviewer_pair_required")
    audit_complete, contract_violations, system_issue = _contract_audit(audit)
    ids_a = set(indexed_a)
    ids_b = set(indexed_b)
    paired_ids = sorted(ids_a & ids_b)

    metrics: dict[str, object] = {
        "completeness": {
            "submission_count_a": len(reviewer_a),
            "submission_count_b": len(reviewer_b),
            "unique_a": len(ids_a),
            "unique_b": len(ids_b),
            "paired": len(paired_ids),
            "duplicate_a": duplicate_a,
            "duplicate_b": duplicate_b,
            "missing_a": max(30 - len(ids_a), len(ids_b - ids_a), 0),
            "missing_b": max(30 - len(ids_b), len(ids_a - ids_b), 0),
        },
        "decision": _dimension(),
        "visibility": _dimension(),
        "primary_action": _dimension(),
        "observed_action_set": _dimension(),
        "target_context": _dimension(),
        "segment": {
            "tp": 0,
            "fp": 0,
            "fn": 0,
            "evaluable": 0,
            "precision": None,
            "recall": None,
            "f1": None,
        },
        "uncertain_abstain": {
            "reviewer_a": sum(_abstains(row) for row in indexed_a.values()),
            "reviewer_b": sum(_abstains(row) for row in indexed_b.values()),
        },
        "automatic_agreement": 0,
        "owner_adjudication": 0,
        "contract_audit_complete": audit_complete,
        "contract_violations": contract_violations,
        "system_issue": system_issue,
    }

    for clip_id in paired_ids:
        left = indexed_a[clip_id]
        right = indexed_b[clip_id]
        decision_a = left.get("decision")
        decision_b = right.get("decision")
        if not isinstance(decision_a, str) or not isinstance(decision_b, str):
            raise Blind30ScoringError("invalid_decision")

        general_abstain = _abstains(left) or _abstains(right)
        decision_metric = metrics["decision"]
        assert isinstance(decision_metric, dict)
        if not general_abstain:
            decision_metric["evaluable"] += 1
            if decision_a == decision_b:
                decision_metric["agreements"] += 1

        automatic = (
            not general_abstain
            and decision_a == decision_b
            and decision_a in {"hold", "exclude"}
        )
        if decision_a == decision_b == "label" and not general_abstain:
            gt_a = _gt(left)
            gt_b = _gt(right)
            if gt_a is None or gt_b is None:
                raise Blind30ScoringError("label_requires_initial_gt")

            visibility = metrics["visibility"]
            primary = metrics["primary_action"]
            observed = metrics["observed_action_set"]
            target_context = metrics["target_context"]
            assert isinstance(visibility, dict)
            assert isinstance(primary, dict)
            assert isinstance(observed, dict)
            assert isinstance(target_context, dict)

            visibility_equal = False
            if gt_a.get("visibility") != "uncertain" and gt_b.get("visibility") != "uncertain":
                visibility["evaluable"] += 1
                visibility_equal = gt_a.get("visibility") == gt_b.get("visibility")
                if visibility_equal:
                    visibility["agreements"] += 1

            primary["evaluable"] += 1
            primary_equal = gt_a.get("primary_action") == gt_b.get("primary_action")
            if primary_equal:
                primary["agreements"] += 1

            observed_a = _as_string_set(
                gt_a.get("observed_actions"), field="observed_actions"
            )
            observed_b = _as_string_set(
                gt_b.get("observed_actions"), field="observed_actions"
            )
            observed["evaluable"] += 1
            observed_equal = observed_a == observed_b
            if observed_equal:
                observed["agreements"] += 1

            context_a = _as_string_set(gt_a.get("context_tags"), field="context_tags")
            context_b = _as_string_set(gt_b.get("context_tags"), field="context_tags")
            target_equal = False
            if gt_a.get("target") != "uncertain" and gt_b.get("target") != "uncertain":
                target_context["evaluable"] += 1
                target_equal = (
                    gt_a.get("target") == gt_b.get("target")
                    and context_a == context_b
                )
                if target_equal:
                    target_context["agreements"] += 1

            segments_a = gt_a.get("segments")
            segments_b = gt_b.get("segments")
            if not isinstance(segments_a, list) or not isinstance(segments_b, list):
                raise Blind30ScoringError("invalid_segments")
            segment_counts = match_segments(segments_a, segments_b)
            segment_metric = metrics["segment"]
            assert isinstance(segment_metric, dict)
            segment_metric["evaluable"] += 1
            for field in ("tp", "fp", "fn"):
                segment_metric[field] += segment_counts[field]
            segments_equal = segment_counts["fp"] == 0 and segment_counts["fn"] == 0

            automatic = (
                visibility_equal
                and primary_equal
                and observed_equal
                and target_equal
                and segments_equal
            )

        if automatic:
            metrics["automatic_agreement"] += 1
        else:
            metrics["owner_adjudication"] += 1

    for name in (
        "decision",
        "visibility",
        "primary_action",
        "observed_action_set",
        "target_context",
    ):
        metric = metrics[name]
        assert isinstance(metric, dict)
        _finalize_dimension(metric)

    segment = metrics["segment"]
    assert isinstance(segment, dict)
    tp, fp, fn = int(segment["tp"]), int(segment["fp"]), int(segment["fn"])
    if int(segment["evaluable"]) > 0:
        precision = tp / (tp + fp) if tp + fp else 1.0
        recall = tp / (tp + fn) if tp + fn else 1.0
        segment["precision"] = round(precision, 6)
        segment["recall"] = round(recall, 6)
        segment["f1"] = (
            round(2 * precision * recall / (precision + recall), 6)
            if precision + recall
            else 0.0
        )
    return metrics


def classify_result(
    metrics: Mapping[str, object],
) -> Literal["PASS", "HOLD", "FAIL"]:
    completeness = metrics["completeness"]
    assert isinstance(completeness, Mapping)
    if (
        completeness["submission_count_a"] != 30
        or completeness["submission_count_b"] != 30
        or completeness["unique_a"] != 30
        or completeness["unique_b"] != 30
        or completeness["paired"] != 30
        or completeness["duplicate_a"] != 0
        or completeness["duplicate_b"] != 0
        or completeness["missing_a"] != 0
        or completeness["missing_b"] != 0
        or not bool(metrics.get("contract_audit_complete"))
        or int(metrics.get("contract_violations", 0)) != 0
    ):
        return "FAIL"

    evaluable_names = (
        "visibility",
        "primary_action",
        "observed_action_set",
        "target_context",
        "segment",
    )
    if bool(metrics.get("system_issue")) or any(
        int(metrics[name]["evaluable"]) < 10  # type: ignore[index]
        for name in evaluable_names
    ):
        return "HOLD"

    decision = metrics["decision"]
    visibility = metrics["visibility"]
    primary = metrics["primary_action"]
    observed = metrics["observed_action_set"]
    target_context = metrics["target_context"]
    segment = metrics["segment"]
    uncertain = metrics["uncertain_abstain"]
    assert isinstance(decision, Mapping)
    assert isinstance(visibility, Mapping)
    assert isinstance(primary, Mapping)
    assert isinstance(observed, Mapping)
    assert isinstance(target_context, Mapping)
    assert isinstance(segment, Mapping)
    assert isinstance(uncertain, Mapping)

    passes = (
        int(decision["agreements"]) >= 24
        and int(visibility["agreements"]) >= 24
        and int(primary["agreements"]) >= 24
        and float(observed["rate"]) >= 0.80
        and float(target_context["rate"]) >= 0.80
        and float(segment["f1"]) >= 0.80
        and int(uncertain["reviewer_a"]) <= 6
        and int(uncertain["reviewer_b"]) <= 6
        and int(metrics["owner_adjudication"]) <= 6
    )
    return "PASS" if passes else "FAIL"


def _canonical_bytes(value: Mapping[str, object]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def write_report(path: Path, report: Mapping[str, object]) -> str:
    payload = _canonical_bytes(report)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_mapping(path: Path) -> Mapping[str, object]:
    value = json.loads(path.read_text())
    if not isinstance(value, Mapping):
        raise Blind30ScoringError(f"invalid_json_object:{path}")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Formal Blind30 raw submission scorer")
    parser.add_argument("--submissions", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    for path in (args.submissions, args.manifest, args.out):
        if not path.is_absolute():
            parser.error(f"absolute path required: {path}")

    try:
        resolved_out = args.out.resolve()
        if resolved_out in {args.submissions.resolve(), args.manifest.resolve()}:
            raise Blind30ScoringError("output_aliases_input")
        payload = _read_mapping(args.submissions)
        manifest = _read_mapping(args.manifest)
        reviewer_a = payload.get("reviewer_a")
        reviewer_b = payload.get("reviewer_b")
        audit = payload.get("audit")
        clips = manifest.get("clips")
        manifest_fingerprints = manifest.get("reviewer_fingerprints")
        if (
            not isinstance(reviewer_a, list)
            or not isinstance(reviewer_b, list)
            or not isinstance(audit, Mapping)
            or not isinstance(clips, list)
            or not isinstance(manifest_fingerprints, list)
        ):
            raise Blind30ScoringError("invalid_submission_or_manifest_shape")
        expected_ids = {
            row["clip_id"]
            for row in clips
            if isinstance(row, Mapping) and isinstance(row.get("clip_id"), str)
        }
        actual_a = {row.get("clip_id") for row in reviewer_a if isinstance(row, Mapping)}
        actual_b = {row.get("clip_id") for row in reviewer_b if isinstance(row, Mapping)}
        if len(expected_ids) != 30 or actual_a != expected_ids or actual_b != expected_ids:
            raise Blind30ScoringError("manifest_submission_set_mismatch")

        fingerprints = [
            _reviewer_fingerprint(reviewer_a),
            _reviewer_fingerprint(reviewer_b),
        ]
        if fingerprints != manifest_fingerprints:
            raise Blind30ScoringError("manifest_reviewer_pair_mismatch")
        metrics = score_blind30(reviewer_a, reviewer_b, audit=audit)
        report = {
            "schema": "rba-blind30-report-v1",
            "scorer_version": SCORER_VERSION,
            "manifest_sha256": hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
            "verdict": classify_result(metrics),
            "metrics": metrics,
        }
        digest = write_report(args.out, report)
        print(f"RBA_BLIND30_SCORE={report['verdict']}")
        print(f"REPORT_SHA256={digest}")
        return 0
    except (Blind30ScoringError, OSError, json.JSONDecodeError) as exc:
        print(f"RBA_BLIND30_SCORE_BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
