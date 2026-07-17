"""threshold tolerance fix 마이그레이션 정적 계약 테스트.

Mac mini canary 실측 결함: clip_prelabels.threshold=real(float4) vs payload numeric exact 비교로
fn_insert_python_evidence_run 이 22023 오탐 → run 0/failed_retryable. 이 fix 는 원본 migration 을
수정하지 않고 CREATE OR REPLACE 로 threshold 만 1e-6 tolerance 로 바꾸며, 기존 H3/H4 검증을 전부 보존한다.
"""

from __future__ import annotations

from pathlib import Path

FIX = Path("migrations/2026-07-17_python_evidence_threshold_tolerance.sql")
ORIG = Path("migrations/2026-07-17_python_evidence_universal_worker.sql")


def _fix() -> str:
    return FIX.read_text().lower()


def test_fix_file_exists_and_is_create_or_replace():
    assert FIX.exists()
    t = _fix()
    assert "create or replace function public.fn_insert_python_evidence_run(p_run jsonb)" in t
    # forward-only: 새 테이블/컬럼 생성 없음
    assert "create table" not in t
    assert "drop function" not in t  # 원본 함수 drop 하지 않음(replace)


def test_threshold_tolerance_contract():
    t = _fix()
    # payload threshold null/비-number 차단
    assert "jsonb_typeof(p_run->'threshold') is distinct from 'number'" in t
    # 1e-6 tolerance 비교 (double precision)
    assert "abs(pl.threshold::double precision - (p_run->>'threshold')::double precision) > 1e-6" in t
    # 기존 numeric exact 비교(버그)는 제거됨
    assert "pl.threshold is distinct from nullif(p_run->>'threshold','')::numeric" not in t


def test_h3_checks_preserved():
    t = _fix()
    # job 잠금 + payload 일치
    assert "where id=(p_run->>'job_id')::uuid for update" in t
    assert "run payload does not match job (clip/schema/algorithm)" in t
    # prelabel clip 일치 + identity
    assert "prelabel belongs to a different clip" in t
    assert "run provenance does not match linked prelabel identity" in t
    # 나머지 6 provenance 컬럼 IS DISTINCT FROM 보존
    for col in ("model_name", "model_version", "checkpoint_sha256", "sampler_version",
                "schema_version", "frames_sampled"):
        assert f"pl.{col} is distinct from" in t


def test_h4_json_checks_preserved():
    t = _fix()
    assert "must be a json object" in t
    assert "must be a json array" in t
    assert "exceeds point cap 256" in t
    assert "jsonb_typeof(e->'t') = 'number'" in t
    assert "(e->>'value')::numeric >= 0" in t
    assert "jsonb_array_elements" in t


def test_security_invoker_empty_search_path_and_grant():
    t = _fix()
    assert "security invoker set search_path=''" in t
    assert "grant execute on function public.fn_insert_python_evidence_run(jsonb) to service_role" in t


def test_original_migration_untouched_reference():
    # 원본 파일은 여전히 존재하며 버그 있는 numeric 비교를 그대로 보유(이 fix 가 원본을 수정하지 않았음을 방증).
    assert ORIG.exists()
    o = ORIG.read_text().lower()
    assert "pl.threshold is distinct from nullif(p_run->>'threshold','')::numeric" in o
