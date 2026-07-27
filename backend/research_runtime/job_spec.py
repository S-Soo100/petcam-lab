from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from backend.research_runtime.handlers import handler_for

_TOP_FIELDS = {
    "schema_version",
    "job_id",
    "task_id",
    "handler",
    "handler_args",
    "manifest_blob_sha",
    "manifest_commit_sha",
    "repo_head",
    "expected_host",
    "budget",
    "resources",
    "privacy_class",
}
_BUDGET_FIELDS = {
    "max_provider_calls",
    "max_cost_krw",
    "max_wall_seconds",
    "deadline",
}
_SECRET_KEYS = {
    "password",
    "secret",
    "token",
    "api_key",
    "webhook",
    "cookie",
    "signed_url",
}
_JOB_ID = re.compile(r"[a-z0-9][a-z0-9._-]{2,79}\Z")
_SHA40 = re.compile(r"[0-9a-f]{40}\Z")
_SHA64 = re.compile(r"[0-9a-f]{64}\Z")


class JobSpecError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class JobSpec:
    schema_version: int
    job_id: str
    task_id: str
    handler: str
    handler_args: Mapping[str, int]
    manifest_blob_sha: str
    manifest_commit_sha: str
    repo_head: str
    expected_host: str
    max_provider_calls: int
    max_cost_krw: int
    max_wall_seconds: int
    deadline: datetime
    resources: tuple[str, ...]
    privacy_class: str
    canonical_bytes: bytes

    @property
    def spec_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes).hexdigest()


def _object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise JobSpecError("duplicate_json_key")
        result[key] = value
    return result


def _canonical_string(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise JobSpecError("invalid_string")
    if any(unicodedata.category(char) == "Cc" for char in value):
        raise JobSpecError("invalid_string")
    return value


def _reject_secret_keys(value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in _SECRET_KEYS:
                raise JobSpecError("secret_field_forbidden")
            _reject_secret_keys(child)
    elif isinstance(value, list):
        for child in value:
            _reject_secret_keys(child)


def _nonnegative_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise JobSpecError("invalid_budget")
    return value


def parse_job_spec(path: Path, *, now: datetime) -> JobSpec:
    try:
        raw_bytes = path.read_bytes()
        raw = json.loads(raw_bytes, object_pairs_hook=_object_pairs)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise JobSpecError("invalid_json") from error
    if not isinstance(raw, dict) or set(raw) != _TOP_FIELDS:
        raise JobSpecError("invalid_fields")
    _reject_secret_keys(raw)
    if raw["schema_version"] != 1:
        raise JobSpecError("invalid_schema_version")
    job_id = _canonical_string(raw["job_id"])
    if _JOB_ID.fullmatch(job_id) is None:
        raise JobSpecError("invalid_job_id")
    task_id = _canonical_string(raw["task_id"])
    handler = _canonical_string(raw["handler"])
    try:
        handler_for(handler)
    except ValueError:
        raise JobSpecError("handler_not_allowed") from None
    args = raw["handler_args"]
    if not isinstance(args, dict) or set(args) != {"steps", "step_seconds"}:
        raise JobSpecError("invalid_handler_args")
    if any(isinstance(value, bool) or not isinstance(value, int) for value in args.values()):
        raise JobSpecError("invalid_handler_args")
    if not 1 <= args["steps"] <= 100 or not 0 <= args["step_seconds"] <= 60:
        raise JobSpecError("invalid_handler_args")
    blob_sha = _canonical_string(raw["manifest_blob_sha"])
    commit_sha = _canonical_string(raw["manifest_commit_sha"])
    repo_head = _canonical_string(raw["repo_head"])
    if _SHA64.fullmatch(blob_sha) is None:
        raise JobSpecError("invalid_manifest_blob_sha")
    if _SHA40.fullmatch(commit_sha) is None or _SHA40.fullmatch(repo_head) is None:
        raise JobSpecError("invalid_commit_sha")
    budget = raw["budget"]
    if not isinstance(budget, dict) or set(budget) != _BUDGET_FIELDS:
        raise JobSpecError("invalid_budget")
    provider_calls = _nonnegative_int(budget["max_provider_calls"])
    cost = _nonnegative_int(budget["max_cost_krw"])
    wall = _nonnegative_int(budget["max_wall_seconds"])
    if provider_calls != 0 or cost != 0 or wall < 1:
        raise JobSpecError("invalid_budget")
    deadline_text = _canonical_string(budget["deadline"])
    try:
        deadline = datetime.fromisoformat(deadline_text)
    except ValueError:
        raise JobSpecError("invalid_deadline") from None
    if deadline.tzinfo is None or deadline.utcoffset() is None or deadline <= now:
        raise JobSpecError("expired_deadline")
    resources = raw["resources"]
    if resources != []:
        raise JobSpecError("invalid_resources")
    privacy = _canonical_string(raw["privacy_class"])
    if privacy != "internal":
        raise JobSpecError("invalid_privacy_class")
    canonical = json.dumps(
        raw,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return JobSpec(
        schema_version=1,
        job_id=job_id,
        task_id=task_id,
        handler=handler,
        handler_args=MappingProxyType(dict(args)),
        manifest_blob_sha=blob_sha,
        manifest_commit_sha=commit_sha,
        repo_head=repo_head,
        expected_host=_canonical_string(raw["expected_host"]),
        max_provider_calls=provider_calls,
        max_cost_krw=cost,
        max_wall_seconds=wall,
        deadline=deadline,
        resources=(),
        privacy_class=privacy,
        canonical_bytes=canonical,
    )
