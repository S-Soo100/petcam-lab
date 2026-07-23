"""쳇바퀴 10분 경계 교정 replay runner 계약 테스트.

fail-closed(입력 SHA) · 결정론 · span 불변식 · effective_params · BLIND 헤더 비노출.
네트워크·DB·R2 의존 0 (fixture 는 tmp_path 로컬 JSON).
"""
import hashlib
import json

import pytest

from scripts import run_wheel_boundary_correction as bc

_FILES = ["EVIDENCE-AUDIT.json", "frozen-cohort.json", "wheel-roi-profile-v1.json"]


def _sig_dict(cid, started_at, mean=0.02, peak=0.03, ph=0, mode="ir"):
    return {
        "signature": {
            "clip_id": cid, "started_at": started_at, "duration_sec": 30.0, "mode": mode,
            "roi_motion_mean": mean, "roi_motion_peak": peak, "roi_periodicity": 0.5,
            "perceptual_hash": ph, "evidence_quality": "ok", "evidence_score": 1.0,
            "novelty": False, "frames_used": 9,
        }
    }


def _make_fixture(d):
    d.mkdir(parents=True, exist_ok=True)
    profile = {
        "profile_id": "fixture",
        "grouping_params": {
            "max_gap_sec": 600.0, "wheel_motion_floor": 0.01, "hamming_threshold": 7,
            "motion_tolerance": 0.02, "novelty_min_hamming": 6,
        },
    }
    audit = {
        "fresh": [
            _sig_dict("a", "2026-07-19T03:00:00+00:00"),
            _sig_dict("b", "2026-07-19T03:01:00+00:00"),
            _sig_dict("c", "2026-07-19T03:02:00+00:00"),
        ],
        "known_wheel": [
            _sig_dict("k1", "2026-07-19T04:00:00+00:00"),
            _sig_dict("k2", "2026-07-19T04:01:00+00:00"),
            _sig_dict("k3", "2026-07-19T04:02:00+00:00"),
        ],
    }
    (d / "wheel-roi-profile-v1.json").write_text(json.dumps(profile), encoding="utf-8")
    (d / "EVIDENCE-AUDIT.json").write_text(json.dumps(audit), encoding="utf-8")
    (d / "frozen-cohort.json").write_text(json.dumps({"clip_ids": ["a", "b", "c"]}), encoding="utf-8")


def _shas(d):
    return {n: hashlib.sha256((d / n).read_bytes()).hexdigest() for n in _FILES}


def test_runner_input_sha_mismatch_fails_closed(tmp_path):
    inp = tmp_path / "in"
    out = tmp_path / "out"
    _make_fixture(inp)
    shas = _shas(inp)
    # 한 byte 변경 → SHA 불일치
    p = inp / "EVIDENCE-AUDIT.json"
    p.write_text(p.read_text() + " ", encoding="utf-8")
    with pytest.raises(bc.InputShaMismatch):
        bc.run(inp, out, expected_shas=shas)
    assert not (out / "RESULT.json").exists()
    assert not (out / "BLIND-REVIEW.csv").exists()


def test_runner_deterministic_span_params_and_blind_headers(tmp_path):
    inp = tmp_path / "in"
    _make_fixture(inp)
    shas = _shas(inp)
    ra = bc.run(inp, tmp_path / "a", expected_shas=shas)
    rb = bc.run(inp, tmp_path / "b", expected_shas=shas)

    assert ra["result_sha256"] == rb["result_sha256"]
    assert ra["span_violation_count"] == 0
    assert ra["effective_params"] == {
        "max_inter_clip_gap_sec": 600.0,
        "max_episode_span_sec": 600.0,
        "wheel_motion_floor": 0.01,
        "hamming_threshold": 7,
        "motion_tolerance": 0.02,
        "novelty_min_hamming": 6,
    }
    # BLIND-REVIEW.csv 에는 evidence score·motion·hash·provenance 열이 없어야 한다.
    header = (tmp_path / "a" / "BLIND-REVIEW.csv").read_text(encoding="utf-8").splitlines()[0]
    assert header == "group_id,is_representative,clip_id,captured_at,labeling_url,owner_verdict"
    for banned in ("score", "motion", "hash", "provenance", "evidence"):
        assert banned not in header.lower()
