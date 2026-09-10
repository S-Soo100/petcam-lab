"""Durable capture-first pipeline values shared by the manager and workers."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping


class PipelineState(StrEnum):
    SCHEDULED = "scheduled"
    CAPTURING = "capturing"
    QUICK_VERIFYING = "quick_verifying"
    CAPTURED = "captured"
    RAW_UPLOADING = "raw_uploading"
    RAW_UPLOADED = "raw_uploaded"
    FULL_VERIFYING = "full_verifying"
    FINALIZING = "finalizing"
    VERIFIED_UPLOADED = "verified_uploaded"
    CAPTURE_FAILED = "capture_failed"
    QUICK_VERIFICATION_FAILED = "quick_verification_failed"
    RAW_UPLOAD_FAILED = "raw_upload_failed"
    FULL_VERIFICATION_FAILED = "full_verification_failed"
    FINAL_ARTIFACT_FAILED = "final_artifact_failed"
    DB_SYNC_FAILED = "db_sync_failed"
    INTEGRITY_CONFLICT = "integrity_conflict"


@dataclass(frozen=True, slots=True)
class PipelineItem:
    slot_start: str
    camera_key: str
    state: PipelineState
    root: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    raw_upload_attempts: int = 0
    finalize_attempts: int = 0
    next_attempt_at: str | None = None
    updated_at: str = ""


SUCCESS_ORDER = (
    PipelineState.SCHEDULED,
    PipelineState.CAPTURING,
    PipelineState.QUICK_VERIFYING,
    PipelineState.CAPTURED,
    PipelineState.RAW_UPLOADING,
    PipelineState.RAW_UPLOADED,
    PipelineState.FULL_VERIFYING,
    PipelineState.FINALIZING,
    PipelineState.VERIFIED_UPLOADED,
)

RETRY_TARGETS = {
    PipelineState.CAPTURE_FAILED: PipelineState.CAPTURING,
    PipelineState.QUICK_VERIFICATION_FAILED: PipelineState.QUICK_VERIFYING,
    PipelineState.RAW_UPLOAD_FAILED: PipelineState.RAW_UPLOADING,
    PipelineState.FULL_VERIFICATION_FAILED: PipelineState.FULL_VERIFYING,
    PipelineState.FINAL_ARTIFACT_FAILED: PipelineState.FINALIZING,
    PipelineState.DB_SYNC_FAILED: PipelineState.FINALIZING,
}


def pipeline_transition_allowed(current: PipelineState, target: PipelineState) -> bool:
    if current == target:
        return True
    if current in RETRY_TARGETS:
        return RETRY_TARGETS[current] == target
    if current in SUCCESS_ORDER and target in SUCCESS_ORDER:
        return SUCCESS_ORDER.index(target) > SUCCESS_ORDER.index(current)
    failures = {
        PipelineState.CAPTURE_FAILED,
        PipelineState.QUICK_VERIFICATION_FAILED,
        PipelineState.RAW_UPLOAD_FAILED,
        PipelineState.FULL_VERIFICATION_FAILED,
        PipelineState.FINAL_ARTIFACT_FAILED,
        PipelineState.DB_SYNC_FAILED,
        PipelineState.INTEGRITY_CONFLICT,
    }
    return target in failures and current != PipelineState.VERIFIED_UPLOADED
