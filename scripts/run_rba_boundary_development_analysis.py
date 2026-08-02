"""Mac mini에서 사람 사건 경계 development 분석을 SELECT-only로 실행해."""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import stat
import sys
from typing import Any, Iterable


_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path[:0] = [str(_REPO_ROOT)]

from scripts.prepare_rba_sequence_review import manifest_from_base_artifact
from scripts.rba_boundary_development_analysis import (
    PINNED_EXPERIMENT_ID,
    PINNED_MANIFEST_DIGEST,
    AnalysisResult,
    AssignmentRow,
    ResolutionRow,
    StudySnapshot,
    SubmissionRow,
    analyze_study,
    render_public_report,
)
from scripts.seed_rba_boundary_review import load_env_file


ALLOWED_SELECTS = {
    "rba_boundary_review_cohorts": "id,experiment_id,manifest_digest,status",
    "rba_boundary_review_pairs": "id,cohort_id,ordinal,pair_digest,gap_sec,gap_bin",
    "rba_boundary_review_assignments": "id,pair_id,reviewer_id,reviewer_role",
    "rba_boundary_review_submissions": (
        "assignment_id,pair_id,reviewer_id,decision,digest,submitted_at"
    ),
    "rba_boundary_review_resolutions": (
        "pair_id,final_decision,digest,resolved_at"
    ),
}


class RunnerSafetyError(RuntimeError):
    """읽기 전용·결정론·비공개 파일 계약을 지키지 못했어."""


def require_env_file_0600(path: Path) -> None:
    if not path.is_file():
        raise RunnerSafetyError("env_file_missing")
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise RunnerSafetyError("env_file_mode_must_be_0600")


def create_private_output(path: Path) -> None:
    if path.exists():
        raise RunnerSafetyError("output_exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.mkdir(mode=0o700)
        path.chmod(0o700)
    except FileExistsError as exc:
        raise RunnerSafetyError("output_exists") from exc


def write_new_file(path: Path, payload: bytes, *, mode: int) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        descriptor = os.open(path, flags, mode)
    except FileExistsError as exc:
        raise RunnerSafetyError("artifact_already_exists") from exc
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        path.chmod(mode)
    except Exception:
        raise


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _stable_reorder(items: Iterable[Any], salt: bytes) -> tuple[Any, ...]:
    def key(item: Any) -> bytes:
        if dataclasses.is_dataclass(item):
            value = dataclasses.asdict(item)
        else:
            value = item
        return hmac.new(salt, _canonical_bytes(value), hashlib.sha256).digest()

    return tuple(sorted(items, key=key))


def analyze_three_passes(
    snapshot: StudySnapshot,
    manifest: dict[str, object],
    salt: bytes,
) -> AnalysisResult:
    reversed_snapshot = dataclasses.replace(
        snapshot,
        effective_pairs=tuple(reversed(snapshot.effective_pairs)),
        assignments=tuple(reversed(snapshot.assignments)),
        submissions=tuple(reversed(snapshot.submissions)),
        resolutions=tuple(reversed(snapshot.resolutions)),
    )
    shuffled_snapshot = dataclasses.replace(
        snapshot,
        effective_pairs=_stable_reorder(snapshot.effective_pairs, salt),
        assignments=_stable_reorder(snapshot.assignments, salt),
        submissions=_stable_reorder(snapshot.submissions, salt),
        resolutions=_stable_reorder(snapshot.resolutions, salt),
    )
    results = (
        analyze_study(snapshot, manifest, salt),
        analyze_study(reversed_snapshot, manifest, salt),
        analyze_study(shuffled_snapshot, manifest, salt),
    )
    private_hashes = {row.private_payload_sha256 for row in results}
    public_hashes = {row.public_report_sha256 for row in results}
    if len(private_hashes) != 1 or len(public_hashes) != 1:
        raise RunnerSafetyError("three_pass_mismatch")
    return results[0]


def _select_all(query: Any, *, identity: str, page_size: int = 1000) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    seen: set[object] = set()
    start = 0
    while True:
        response = query.range(start, start + page_size - 1).execute()
        page = response.data
        if not isinstance(page, list):
            raise RunnerSafetyError("invalid_select_response")
        for raw in page:
            if not isinstance(raw, dict):
                raise RunnerSafetyError("invalid_select_row")
            value = raw.get(identity)
            if value is None or value in seen:
                raise RunnerSafetyError("duplicate_or_missing_select_identity")
            seen.add(value)
            rows.append(dict(raw))
        if len(page) < page_size:
            break
        start += page_size
    return tuple(rows)


def load_study_snapshot(client: Any) -> StudySnapshot:
    cohorts = _select_all(
        client.table("rba_boundary_review_cohorts")
        .select(ALLOWED_SELECTS["rba_boundary_review_cohorts"])
        .eq("experiment_id", PINNED_EXPERIMENT_ID)
        .eq("manifest_digest", PINNED_MANIFEST_DIGEST),
        identity="id",
    )
    if len(cohorts) != 1 or cohorts[0].get("status") not in {
        "development_open",
        "development_frozen",
        "closed",
    }:
        raise RunnerSafetyError("cohort_not_exact_or_not_complete")
    cohort_id = str(cohorts[0]["id"])
    pairs = _select_all(
        client.table("rba_boundary_review_pairs")
        .select(ALLOWED_SELECTS["rba_boundary_review_pairs"])
        .eq("cohort_id", cohort_id)
        .order("ordinal"),
        identity="id",
    )
    pair_ids = [str(row["id"]) for row in pairs]
    if len(pair_ids) != 120:
        raise RunnerSafetyError("pair_count_drift")
    assignments = _select_all(
        client.table("rba_boundary_review_assignments")
        .select(ALLOWED_SELECTS["rba_boundary_review_assignments"])
        .in_("pair_id", pair_ids)
        .order("id"),
        identity="id",
    )
    effective_ids = {str(row["pair_id"]) for row in assignments}
    submissions = _select_all(
        client.table("rba_boundary_review_submissions")
        .select(ALLOWED_SELECTS["rba_boundary_review_submissions"])
        .in_("pair_id", sorted(effective_ids))
        .order("assignment_id"),
        identity="assignment_id",
    )
    resolutions = _select_all(
        client.table("rba_boundary_review_resolutions")
        .select(ALLOWED_SELECTS["rba_boundary_review_resolutions"])
        .in_("pair_id", sorted(effective_ids))
        .order("pair_id"),
        identity="pair_id",
    )
    effective_pairs = tuple({
        "pair_id": str(row["id"]),
        "pair_digest": str(row["pair_digest"]),
        "ordinal": int(row["ordinal"]),
        "gap_sec": float(row["gap_sec"]),
        "gap_bin": str(row["gap_bin"]),
    } for row in pairs if str(row["id"]) in effective_ids)
    return StudySnapshot(
        experiment_id=str(cohorts[0]["experiment_id"]),
        manifest_digest=str(cohorts[0]["manifest_digest"]),
        total_pair_count=len(pairs),
        effective_pairs=effective_pairs,
        assignments=tuple(AssignmentRow(
            assignment_id=str(row["id"]),
            pair_id=str(row["pair_id"]),
            reviewer_id=str(row["reviewer_id"]),
            reviewer_role=str(row["reviewer_role"]),
        ) for row in assignments),
        submissions=tuple(SubmissionRow(
            assignment_id=str(row["assignment_id"]),
            pair_id=str(row["pair_id"]),
            reviewer_id=str(row["reviewer_id"]),
            decision=str(row["decision"]),  # type: ignore[arg-type]
        ) for row in submissions),
        resolutions=tuple(ResolutionRow(
            pair_id=str(row["pair_id"]),
            final_decision=str(row["final_decision"]),  # type: ignore[arg-type]
        ) for row in resolutions),
    )


def load_pinned_manifest(path: Path) -> dict[str, object]:
    source = path / "boundary-pairs.json" if path.is_dir() else path
    if not source.is_file():
        raise RunnerSafetyError("base_artifact_missing")
    raw = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise RunnerSafetyError("base_artifact_invalid")
    manifest = manifest_from_base_artifact(raw)
    if (
        manifest.get("experiment_id") != PINNED_EXPERIMENT_ID
        or manifest.get("manifest_sha256") != PINNED_MANIFEST_DIGEST
    ):
        raise RunnerSafetyError("regenerated_manifest_mismatch")
    return manifest


def _private_artifact(result: AnalysisResult) -> bytes:
    payload = result.to_private_dict()
    payload["private_payload_sha256"] = result.private_payload_sha256
    payload["public_report_sha256"] = result.public_report_sha256
    payload["determinism_passes"] = 3
    return _canonical_bytes(payload)


def run(
    *,
    client: Any,
    base_artifact: Path,
    output_dir: Path,
    report_path: Path,
) -> AnalysisResult:
    if report_path.exists():
        raise RunnerSafetyError("report_already_exists")
    create_private_output(output_dir)
    salt = secrets.token_bytes(32)
    write_new_file(output_dir / "run-salt.bin", salt, mode=0o600)
    manifest = load_pinned_manifest(base_artifact)
    snapshot = load_study_snapshot(client)
    result = analyze_three_passes(snapshot, manifest, salt)
    write_new_file(
        output_dir / "analysis-private.json",
        _private_artifact(result),
        mode=0o600,
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    write_new_file(
        report_path,
        render_public_report(result).encode("utf-8"),
        mode=0o644,
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-artifact", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    require_env_file_0600(args.env_file)
    if args.output_dir.exists() or args.report.exists():
        raise RunnerSafetyError("output_or_report_already_exists")
    load_env_file(args.env_file)
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RunnerSafetyError("supabase_env_missing")
    from supabase import create_client

    result = run(
        client=create_client(url, key),
        base_artifact=args.base_artifact,
        output_dir=args.output_dir,
        report_path=args.report,
    )
    print(
        "RBA_BOUNDARY_DEVELOPMENT_DONE "
        f"gt={result.gt_verdict} utility={result.utility_verdict} "
        f"private_sha256={result.private_payload_sha256} "
        f"public_sha256={result.public_report_sha256} writes_db=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
