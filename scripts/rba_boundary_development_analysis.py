"""사람 사건 경계 development 표본을 결정론적으로 분석해.

이 모듈은 I/O를 하지 않아. production SELECT와 파일 쓰기는 별도 runner가 담당해.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, replace
from typing import Literal, Mapping, Sequence


Decision = Literal["same_event", "different_event", "uncertain"]
DECISIONS: tuple[Decision, ...] = ("same_event", "different_event", "uncertain")
PINNED_EXPERIMENT_ID = "rba-event-sequence-review-v2"
PINNED_MANIFEST_DIGEST = (
    "edd3f2c230adacb70c0b8bc70072eb632eb0ac48718bdd1ffbeca88649e9dfca"
)
EXPECTED_COUNTS = (120, 74, 148, 148, 26)
THRESHOLD_CANDIDATES = (0, 5, 15, 30, 60, 120)


class AnalysisBlocked(RuntimeError):
    """입력 무결성이 고정 계약과 달라 분석을 중단했어."""


@dataclass(frozen=True, slots=True)
class AssignmentRow:
    assignment_id: str
    pair_id: str
    reviewer_id: str
    reviewer_role: str


@dataclass(frozen=True, slots=True)
class SubmissionRow:
    assignment_id: str
    pair_id: str
    reviewer_id: str
    decision: Decision


@dataclass(frozen=True, slots=True)
class ResolutionRow:
    pair_id: str
    final_decision: Decision


@dataclass(frozen=True, slots=True)
class StudySnapshot:
    experiment_id: str
    manifest_digest: str
    total_pair_count: int
    effective_pairs: tuple[dict[str, object], ...]
    assignments: tuple[AssignmentRow, ...]
    submissions: tuple[SubmissionRow, ...]
    resolutions: tuple[ResolutionRow, ...]


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    gt_verdict: str
    utility_verdict: str
    counts: dict[str, int]
    raw_agreement: float
    cohen_kappa: float | None
    confusion_matrix: tuple[tuple[int, int, int], ...]
    reviewer_decision_counts: tuple[dict[str, int], dict[str, int]]
    uncertain_submission_rate: float
    owner_intervention_rate: float
    owner_initial_adoption_rate: float | None
    final_decision_counts: dict[str, int]
    source_clip_count: int
    human_event_count: int
    event_reduction: float
    threshold_rows: tuple[dict[str, int], ...]
    selected_threshold_sec: int | None
    gap_bin_counts: dict[str, int]
    anonymous_camera_night_counts: dict[str, int]
    event_groups: tuple[tuple[str, ...], ...]
    final_boundaries: tuple[dict[str, str], ...]
    private_payload_sha256: str = ""
    public_report_sha256: str = ""

    def to_private_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload.pop("private_payload_sha256", None)
        payload.pop("public_report_sha256", None)
        return payload


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _token(salt: bytes, namespace: str, raw: object) -> str:
    return hmac.new(
        salt,
        f"{namespace}\0{raw}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:16]


def _blocked(code: str, detail: str = "") -> AnalysisBlocked:
    suffix = f":{detail}" if detail else ""
    return AnalysisBlocked(f"BLOCKED_GT_INTEGRITY:{code}{suffix}")


def _validate_manifest(manifest: Mapping[str, object], snapshot: StudySnapshot) -> list[dict[str, object]]:
    if (
        snapshot.experiment_id != PINNED_EXPERIMENT_ID
        or snapshot.manifest_digest != PINNED_MANIFEST_DIGEST
        or manifest.get("experiment_id") != PINNED_EXPERIMENT_ID
        or manifest.get("manifest_sha256") != PINNED_MANIFEST_DIGEST
    ):
        raise _blocked("COHORT_PROVENANCE")
    raw_pairs = manifest.get("pairs")
    if not isinstance(raw_pairs, list) or len(raw_pairs) != 120:
        raise _blocked("COUNT_DRIFT", "manifest_pairs")
    pairs: list[dict[str, object]] = []
    seen_digests: set[str] = set()
    previous_by_run: dict[int, dict[str, object]] = {}
    for raw in raw_pairs:
        if not isinstance(raw, dict):
            raise _blocked("ADJACENCY", "pair_shape")
        pair = dict(raw)
        try:
            digest = str(pair["pair_digest"])
            run = int(pair["run_ordinal"])
            ordinal = int(pair["ordinal"])
            left = str(pair["left_clip_id"])
            right = str(pair["right_clip_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise _blocked("ADJACENCY", "missing_fields") from exc
        if digest in seen_digests or left == right:
            raise _blocked("ADJACENCY", "duplicate_or_self_edge")
        previous = previous_by_run.get(run)
        if previous is not None:
            if int(previous["ordinal"]) >= ordinal or str(previous["right_clip_id"]) != left:
                raise _blocked("ADJACENCY", "broken_run")
        previous_by_run[run] = pair
        seen_digests.add(digest)
        pairs.append(pair)
    return pairs


def _validate_snapshot(
    snapshot: StudySnapshot,
    manifest_pairs: Sequence[dict[str, object]],
) -> tuple[dict[str, dict[str, object]], dict[str, tuple[SubmissionRow, SubmissionRow]]]:
    counts = (
        snapshot.total_pair_count,
        len(snapshot.effective_pairs),
        len(snapshot.assignments),
        len(snapshot.submissions),
        len(snapshot.resolutions),
    )
    if counts != EXPECTED_COUNTS:
        raise _blocked("COUNT_DRIFT", str(counts))

    manifest_by_digest = {str(pair["pair_digest"]): pair for pair in manifest_pairs}
    effective: dict[str, dict[str, object]] = {}
    for row in snapshot.effective_pairs:
        pair_id = str(row.get("pair_id", ""))
        digest = str(row.get("pair_digest", ""))
        source = manifest_by_digest.get(digest)
        if not pair_id or source is None or pair_id in effective:
            raise _blocked("PAIR_PROVENANCE")
        if int(row.get("ordinal", -1)) != int(source["ordinal"]):
            raise _blocked("PAIR_PROVENANCE", "ordinal")
        if float(row.get("gap_sec", -1)) != float(source["gap_sec"]):
            raise _blocked("PAIR_PROVENANCE", "gap")
        if str(row.get("gap_bin", "")) != str(source["gap_bin"]):
            raise _blocked("PAIR_PROVENANCE", "gap_bin")
        effective[pair_id] = source

    assignments_by_id: dict[str, AssignmentRow] = {}
    assignments_by_pair: dict[str, list[AssignmentRow]] = defaultdict(list)
    for assignment in snapshot.assignments:
        if assignment.assignment_id in assignments_by_id or assignment.pair_id not in effective:
            raise _blocked("ASSIGNMENT_BIJECTION")
        assignments_by_id[assignment.assignment_id] = assignment
        assignments_by_pair[assignment.pair_id].append(assignment)
    for pair_id in effective:
        rows = assignments_by_pair[pair_id]
        if (
            len(rows) != 2
            or len({row.reviewer_id for row in rows}) != 2
            or {row.reviewer_role.lower() for row in rows} != {"owner", "peer"}
        ):
            raise _blocked("ASSIGNMENT_BIJECTION", "two_distinct_reviewers")

    submissions_by_assignment: dict[str, SubmissionRow] = {}
    submissions_by_pair: dict[str, list[SubmissionRow]] = defaultdict(list)
    for submission in snapshot.submissions:
        assignment = assignments_by_id.get(submission.assignment_id)
        if (
            assignment is None
            or submission.assignment_id in submissions_by_assignment
            or assignment.pair_id != submission.pair_id
            or assignment.reviewer_id != submission.reviewer_id
            or submission.decision not in DECISIONS
        ):
            raise _blocked("SUBMISSION_BIJECTION")
        submissions_by_assignment[submission.assignment_id] = submission
        submissions_by_pair[submission.pair_id].append(submission)
    if set(submissions_by_assignment) != set(assignments_by_id):
        raise _blocked("SUBMISSION_BIJECTION", "missing")

    ordered_submissions: dict[str, tuple[SubmissionRow, SubmissionRow]] = {}
    assignment_role = {
        row.assignment_id: row.reviewer_role for row in snapshot.assignments
    }
    for pair_id, rows in submissions_by_pair.items():
        ordered = sorted(
            rows,
            key=lambda row: (
                0 if assignment_role[row.assignment_id].lower() == "owner" else 1,
                row.reviewer_id,
            ),
        )
        ordered_submissions[pair_id] = (ordered[0], ordered[1])

    required_resolution = {
        pair_id
        for pair_id, (first, second) in ordered_submissions.items()
        if first.decision != second.decision
        or "uncertain" in (first.decision, second.decision)
    }
    resolution_ids = [row.pair_id for row in snapshot.resolutions]
    if (
        len(resolution_ids) != len(set(resolution_ids))
        or set(resolution_ids) != required_resolution
        or any(row.final_decision not in DECISIONS for row in snapshot.resolutions)
    ):
        raise _blocked("RESOLUTION_SET_MISMATCH")
    return effective, ordered_submissions


def _cohen_kappa(matrix: tuple[tuple[int, int, int], ...]) -> float | None:
    total = sum(sum(row) for row in matrix)
    if not total:
        return None
    observed = sum(matrix[index][index] for index in range(3)) / total
    row_totals = [sum(row) for row in matrix]
    col_totals = [sum(matrix[row][column] for row in range(3)) for column in range(3)]
    expected = sum(row_totals[index] * col_totals[index] for index in range(3)) / (total * total)
    if expected == 1:
        return 1.0 if observed == 1 else None
    return (observed - expected) / (1 - expected)


def _event_groups(
    effective: Mapping[str, dict[str, object]],
    final: Mapping[str, Decision],
    salt: bytes,
) -> tuple[int, tuple[tuple[str, ...], ...]]:
    parents: dict[str, str] = {}

    def find(node: str) -> str:
        parents.setdefault(node, node)
        while parents[node] != node:
            parents[node] = parents[parents[node]]
            node = parents[node]
        return node

    def union(left: str, right: str) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parents[max(left_root, right_root)] = min(left_root, right_root)

    degree: Counter[str] = Counter()
    for pair_id, source in effective.items():
        left = str(source["left_clip_id"])
        right = str(source["right_clip_id"])
        find(left)
        find(right)
        degree[left] += 1
        degree[right] += 1
        if degree[left] > 2 or degree[right] > 2:
            raise _blocked("ADJACENCY", "branching")
        if final[pair_id] == "same_event":
            union(left, right)

    grouped: dict[str, list[str]] = defaultdict(list)
    for clip in sorted(parents):
        grouped[find(clip)].append(_token(salt, "clip", clip))
    groups = tuple(sorted((tuple(sorted(clips)) for clips in grouped.values())))
    return len(parents), groups


def render_public_report(result: AnalysisResult) -> str:
    threshold = (
        "없음" if result.selected_threshold_sec is None else f"{result.selected_threshold_sec}초"
    )
    kappa = "계산 불가" if result.cohen_kappa is None else f"{result.cohen_kappa:.4f}"
    lines = [
        "# RBA 사건 경계 Development 분석 v1 결과",
        "",
        f"- GT 판정: `{result.gt_verdict}`",
        f"- router utility 판정: `{result.utility_verdict}`",
        f"- 유효 경계: {result.counts['effective_pairs']}개",
        f"- 두 검수자 일치율: {result.raw_agreement:.2%}",
        f"- Cohen's kappa: {kappa}",
        f"- Owner 최종 개입: {result.counts['resolutions']}개 ({result.owner_intervention_rate:.2%})",
        f"- 최종 uncertain: {result.final_decision_counts['uncertain']}개",
        f"- 입력 클립: {result.source_clip_count}개",
        f"- 사람 확정 사건: {result.human_event_count}개",
        f"- 사건 수 감소율: {result.event_reduction:.2%}",
        f"- 안전한 gap threshold: {threshold}",
        "",
        "## 해석",
        "",
        "사람 경계를 사건 단위 입력으로 바꾸는 development 기반의 무결성과 결정론을 검사한 결과야.",
        "agreement와 kappa는 사람 판단의 난도를 설명할 뿐 GT 채택 기준으로 사용하지 않았어.",
        "",
        "## 안전 확인",
        "",
        "- production DB write: 0",
        "- R2/frame/Python Evidence/Gate/VLM/service 호출: 0",
        "- public raw UUID/reviewer/reason/camera/date/secret: 0",
        "",
    ]
    if result.selected_threshold_sec == 0:
        lines[15:15] = [
            "0초는 실용 자동 묶기 기준으로 채택하지 않아 router utility를 보류했어.",
        ]
    return "\n".join(lines)


def analyze_study(
    snapshot: StudySnapshot,
    manifest: dict[str, object],
    salt: bytes,
) -> AnalysisResult:
    if not salt:
        raise _blocked("SALT")
    manifest_pairs = _validate_manifest(manifest, snapshot)
    effective, submissions = _validate_snapshot(snapshot, manifest_pairs)
    resolutions = {row.pair_id: row.final_decision for row in snapshot.resolutions}

    matrix_data = [[0, 0, 0] for _ in range(3)]
    reviewer_counts = [Counter(), Counter()]
    final: dict[str, Decision] = {}
    owner_adoptions = 0
    for pair_id in sorted(effective, key=lambda item: int(effective[item]["ordinal"])):
        first, second = submissions[pair_id]
        first_index = DECISIONS.index(first.decision)
        second_index = DECISIONS.index(second.decision)
        matrix_data[first_index][second_index] += 1
        reviewer_counts[0][first.decision] += 1
        reviewer_counts[1][second.decision] += 1
        if first.decision == second.decision and first.decision != "uncertain":
            final[pair_id] = first.decision
        else:
            final[pair_id] = resolutions[pair_id]
            owner_submission = next(
                (
                    row
                    for row in (first, second)
                    if next(
                        assignment.reviewer_role.lower() == "owner"
                        for assignment in snapshot.assignments
                        if assignment.assignment_id == row.assignment_id
                    )
                ),
                None,
            )
            if owner_submission is not None and final[pair_id] == owner_submission.decision:
                owner_adoptions += 1

    matrix = tuple(tuple(row) for row in matrix_data)
    agreement_count = sum(matrix[index][index] for index in range(3))
    uncertain_submissions = sum(
        row.decision == "uncertain" for row in snapshot.submissions
    )
    final_counts = Counter(final.values())
    source_clip_count, groups = _event_groups(effective, final, salt)
    human_event_count = len(groups)
    event_reduction = (
        1 - human_event_count / source_clip_count if source_clip_count else 0.0
    )

    threshold_rows: list[dict[str, int]] = []
    for threshold in THRESHOLD_CANDIDATES:
        overmerge = 0
        oversplit = 0
        for pair_id, source in effective.items():
            predicted_same = float(source["gap_sec"]) <= threshold
            if predicted_same and final[pair_id] == "different_event":
                overmerge += 1
            if not predicted_same and final[pair_id] == "same_event":
                oversplit += 1
        threshold_rows.append({
            "threshold_sec": threshold,
            "overmerge": overmerge,
            "oversplit": oversplit,
        })
    safe = [row for row in threshold_rows if row["overmerge"] == 0]
    selected = min(
        safe,
        key=lambda row: (row["oversplit"], row["threshold_sec"]),
        default=None,
    )
    has_uncertain = final_counts["uncertain"] > 0
    gt_verdict = (
        "HOLD_UNRESOLVED_BOUNDARY"
        if has_uncertain
        else "DEVELOPMENT_EVENT_GT_READY_FOR_LOCAL_VLM_BASELINE"
    )
    utility_verdict = (
        "PASS"
        if (
            event_reduction >= 0.15
            and selected is not None
            and int(selected["threshold_sec"]) > 0
        )
        else "EVENT_GT_READY_ROUTER_UTILITY_HOLD"
    )

    gap_bin_counts = Counter(str(source["gap_bin"]) for source in effective.values())
    camera_night_counts: Counter[str] = Counter()
    for source in effective.values():
        raw_label = f"{source.get('camera_id', '')}\0{source.get('activity_day_kst', '')}"
        camera_night_counts[f"night-{_token(salt, 'camera-night', raw_label)}"] += 1
    final_boundaries = tuple({
        "pair": _token(salt, "pair", pair_id),
        "decision": final[pair_id],
    } for pair_id in sorted(final, key=lambda item: int(effective[item]["ordinal"])))

    result = AnalysisResult(
        gt_verdict=gt_verdict,
        utility_verdict=utility_verdict,
        counts={
            "total_pairs": snapshot.total_pair_count,
            "effective_pairs": len(effective),
            "assignments": len(snapshot.assignments),
            "submissions": len(snapshot.submissions),
            "resolutions": len(snapshot.resolutions),
        },
        raw_agreement=agreement_count / len(effective),
        cohen_kappa=_cohen_kappa(matrix),
        confusion_matrix=matrix,
        reviewer_decision_counts=tuple(
            {decision: counts[decision] for decision in DECISIONS}
            for counts in reviewer_counts
        ),
        uncertain_submission_rate=uncertain_submissions / len(snapshot.submissions),
        owner_intervention_rate=len(snapshot.resolutions) / len(effective),
        owner_initial_adoption_rate=(
            owner_adoptions / len(snapshot.resolutions)
            if snapshot.resolutions
            else None
        ),
        final_decision_counts={decision: final_counts[decision] for decision in DECISIONS},
        source_clip_count=source_clip_count,
        human_event_count=human_event_count,
        event_reduction=event_reduction,
        threshold_rows=tuple(threshold_rows),
        selected_threshold_sec=(
            int(selected["threshold_sec"]) if selected is not None else None
        ),
        gap_bin_counts=dict(sorted(gap_bin_counts.items())),
        anonymous_camera_night_counts=dict(sorted(camera_night_counts.items())),
        event_groups=groups,
        final_boundaries=final_boundaries,
    )
    private_hash = hashlib.sha256(_canonical_bytes(result.to_private_dict())).hexdigest()
    result = replace(result, private_payload_sha256=private_hash)
    public_hash = hashlib.sha256(render_public_report(result).encode("utf-8")).hexdigest()
    return replace(result, public_report_sha256=public_hash)
