"""Disposable PostgreSQL 동시 제출 실증 러너 (이중 블라인드 하드닝 Task 6).

정적 SQL 텍스트 테스트만으로 정상 동작을 주장하지 않는다. 최소 prerequisite schema 를 가진
일회용 postgres:15 컨테이너를 127.0.0.1 에만 바인딩해 띄우고:

  (1) rollback probe(hardening_probe.sql) 로 aggregate 실행·live ownership·cross-object
      identity·event idempotency·canary eligibility 를 한 트랜잭션 안에서 검증하고 전량 ROLLBACK
      → DB_RUNTIME_PROBE_OK, 이후 잔여 synthetic row 0 → PROBE_RESIDUE=0
  (2) 두 psql 세션을 동시에 열어 같은 clip×cohort 제출 경합을 재현 → 두 immutable 제출이 모두
      보존되고 peer_present 다중집합이 {false, true}, finalize 후 auto_compared event 는 정확히 1,
      동일 finalize 재시도에도 1 → DB_CONCURRENCY_PROBE_OK

운영 DB 에는 절대 접속하지 않는다(127.0.0.1/localhost 만 허용). Docker/이미지 부재·컨테이너 기동
실패·마커 누락은 모두 BLOCKED(READY 주장 금지)로 멈춘다.

순수 로직(validate_database_url / parse_probe_rows)만 단위 테스트하고, 컨테이너 오케스트레이션은
얇게 유지한다. 이 파일은 임의로 production migration 을 적용하지 않는다 — 대상은 오직 일회용 컨테이너.
"""

from __future__ import annotations

import argparse
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

CONTAINER_IMAGE = "postgres:15"
LOCAL_HOSTS = {"127.0.0.1", "localhost"}
BLOCKED_VERDICT = "DOUBLE_BLIND_LABELING_HARDENING_BLOCKED_DB_RUNTIME"


class ProbeBlocked(Exception):
    """Docker/이미지/런타임 부재 등으로 실증을 진행할 수 없는 상태. READY 주장 금지 신호."""


class ProbeFailed(Exception):
    """실증은 돌았으나 불변식(동시성/마커/잔여물)이 깨진 상태."""


@dataclass(frozen=True)
class ProbeResult:
    verdict: str
    peer_present: tuple[bool, ...]


# ── 순수 로직(단위 테스트 대상) ──────────────────────────────────────
def validate_database_url(url: str) -> None:
    """DATABASE_URL 이 로컬 일회용 컨테이너만 가리키는지 강제한다(운영 DB 접속 차단)."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if host not in LOCAL_HOSTS:
        raise ProbeBlocked(f"non_local_database_forbidden: host={host!r}")


def _coerce_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"t", "true", "1", "yes"}:
        return True
    if text in {"f", "false", "0", "no", ""}:
        return False
    raise ProbeFailed(f"unparseable peer_present: {value!r}")


def parse_probe_rows(rows: list[dict]) -> ProbeResult:
    """두 동시 제출 결과 행을 판정한다.

    정확히 2개의 immutable 제출이 있고 peer_present 다중집합이 {false, true} 여야
    'DB_CONCURRENCY_PROBE_OK'. 그 외(둘 다 false/true, 개수 불일치)는 'CONCURRENCY_FAILED'.
    """
    presents = tuple(_coerce_bool(r.get("peer_present")) for r in rows)
    if len(presents) == 2 and sorted(presents) == [False, True]:
        return ProbeResult(verdict="DB_CONCURRENCY_PROBE_OK", peer_present=presents)
    return ProbeResult(verdict="CONCURRENCY_FAILED", peer_present=presents)


# ── 컨테이너 오케스트레이션(Docker 필요, 단위 테스트 제외) ────────────
def _run(cmd: list[str], *, timeout: float = 60.0, input_text: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        input=input_text,
    )


def _require_docker() -> None:
    try:
        proc = _run(["docker", "info", "--format", "{{.ServerVersion}}"], timeout=20)
    except FileNotFoundError as exc:
        raise ProbeBlocked("docker_cli_missing") from exc
    except subprocess.TimeoutExpired as exc:
        raise ProbeBlocked("docker_daemon_unresponsive") from exc
    if proc.returncode != 0:
        raise ProbeBlocked(f"docker_daemon_unavailable: {proc.stderr.strip()[:200]}")


def _require_image() -> None:
    # 이미지가 없으면 승인되지 않은 download 가 필요하므로 BLOCKED (임의 pull 금지).
    proc = _run(["docker", "image", "inspect", CONTAINER_IMAGE], timeout=20)
    if proc.returncode != 0:
        raise ProbeBlocked(f"image_unavailable_needs_approved_download: {CONTAINER_IMAGE}")


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _psql(dsn: str, sql: str, *, timeout: float = 60.0, on_error_stop: bool = True) -> subprocess.CompletedProcess:
    args = ["docker", "run", "--rm", "-i", "--network", "host", CONTAINER_IMAGE, "psql", dsn, "-v", "ON_ERROR_STOP=1" if on_error_stop else "ON_ERROR_STOP=0", "-A", "-t"]
    return _run(args, timeout=timeout, input_text=sql)


def _wait_ready(container: str, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        proc = _run(["docker", "exec", container, "pg_isready", "-U", "postgres", "-h", "127.0.0.1"], timeout=15)
        if proc.returncode == 0:
            return
        time.sleep(1.0)
    raise ProbeBlocked("container_not_ready")


def run_concurrency_probe(migration: Path, prerequisites: Path, probe: Path) -> int:
    """일회용 컨테이너에서 runtime + concurrency 실증을 수행하고 마커를 출력한다.

    반환: 0=OK, 1=FAILED. BLOCKED 는 ProbeBlocked 로 상위에서 처리한다.
    """
    _require_docker()
    _require_image()

    container = f"blind-probe-{secrets.token_hex(6)}"
    port = _free_local_port()
    password = secrets.token_hex(16)
    dsn = f"postgresql://postgres:{password}@127.0.0.1:{port}/postgres"
    validate_database_url(dsn)

    tmpdir = Path(tempfile.mkdtemp(prefix="blind-probe-"))
    started = False
    try:
        start = _run(
            [
                "docker", "run", "-d", "--name", container,
                "-e", f"POSTGRES_PASSWORD={password}",
                "-p", f"127.0.0.1:{port}:5432",
                CONTAINER_IMAGE,
            ],
            timeout=60,
        )
        if start.returncode != 0:
            raise ProbeBlocked(f"container_start_failed: {start.stderr.strip()[:200]}")
        started = True
        _wait_ready(container)

        # 1) prerequisite schema + migration 적용.
        for name, path in (("prerequisites", prerequisites), ("migration", migration)):
            proc = _psql(dsn, path.read_text())
            if proc.returncode != 0:
                raise ProbeFailed(f"{name}_apply_failed: {proc.stderr.strip()[:400]}")

        # 2) rollback runtime probe.
        runtime = _psql(dsn, probe.read_text())
        if runtime.returncode != 0 or "DB_RUNTIME_PROBE_OK" not in runtime.stdout:
            raise ProbeFailed(f"runtime_probe_failed: {runtime.stderr.strip()[:400] or runtime.stdout.strip()[:400]}")

        # 잔여 synthetic row 0 (rollback probe 뒤, concurrency 전).
        residue = _psql(
            dsn,
            "SELECT (SELECT count(*) FROM public.motion_clip_review_slots)"
            " + (SELECT count(*) FROM public.motion_clip_blind_submissions)"
            " + (SELECT count(*) FROM public.motion_clip_consensus)"
            " + (SELECT count(*) FROM public.motion_clip_consensus_events);",
        )
        residue_count = int((residue.stdout or "0").strip() or "0")

        # 3) 동시 제출 경합 재현.
        concurrency = _run_concurrency_race(dsn)

        print("DB_RUNTIME_PROBE_OK")
        print(concurrency.verdict)
        print(f"PROBE_RESIDUE={residue_count}")
        if concurrency.verdict != "DB_CONCURRENCY_PROBE_OK" or residue_count != 0:
            return 1
        return 0
    finally:
        if started:
            _run(["docker", "rm", "-f", container], timeout=30)
        for leftover in tmpdir.glob("*"):
            leftover.unlink(missing_ok=True)
        tmpdir.rmdir()


def _run_concurrency_race(dsn: str) -> ProbeResult:
    """setup → 두 psql 세션 동시 제출 → finalize idempotency 검증."""
    owner, a, b, cam, clip = (secrets.token_hex(16) for _ in range(5))
    ids = {
        "owner": _uuid(owner), "a": _uuid(a), "b": _uuid(b),
        "cam": _uuid(cam), "clip": _uuid(clip),
        "tok_a": _uuid(secrets.token_hex(16)), "tok_b": _uuid(secrets.token_hex(16)),
    }
    setup = _SETUP_SQL.format(**ids)
    proc = _psql(dsn, setup)
    if proc.returncode != 0:
        raise ProbeFailed(f"race_setup_failed: {proc.stderr.strip()[:400]}")

    # A 는 consensus 잠금을 잡고 pg_sleep 하는 동안 유지, B 는 A 커밋까지 대기 → A=false, B=true.
    sql_a = _SUBMIT_SQL.format(clip=ids["clip"], reviewer=ids["a"], token=ids["tok_a"], sleep="1.5", tag="A")
    sql_b = _SUBMIT_SQL.format(clip=ids["clip"], reviewer=ids["b"], token=ids["tok_b"], sleep="0", tag="B")

    proc_a = subprocess.Popen(_psql_argv(dsn), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    time.sleep(0.4)  # A 가 consensus 잠금을 먼저 확보하도록.
    proc_b = subprocess.Popen(_psql_argv(dsn), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out_a, _ = proc_a.communicate(sql_a, timeout=30)
    out_b, _ = proc_b.communicate(sql_b, timeout=30)

    rows = [
        {"reviewer": "a", "peer_present": _extract(out_a, "PEER_A=")},
        {"reviewer": "b", "peer_present": _extract(out_b, "PEER_B=")},
    ]
    result = parse_probe_rows(rows)

    # 두 immutable 제출 보존 확인.
    count = _psql(dsn, f"SELECT count(*) FROM public.motion_clip_blind_submissions WHERE clip_id='{ids['clip']}';")
    if int((count.stdout or "0").strip() or "0") != 2:
        raise ProbeFailed("expected exactly two immutable submissions")

    # finalize idempotency: awaiting→agreed 1 event, 재시도에도 1.
    _finalize_and_check(dsn, ids["clip"])
    return result


def _finalize_and_check(dsn: str, clip: str) -> None:
    pair = _psql(dsn, f"SELECT id || '|' || digest FROM public.motion_clip_blind_submissions WHERE clip_id='{clip}' ORDER BY id;")
    lines = [ln for ln in pair.stdout.splitlines() if "|" in ln]
    if len(lines) != 2:
        raise ProbeFailed("finalize_pair_lookup_failed")
    (id_a, dig_a), (id_b, dig_b) = (ln.split("|", 1) for ln in lines)
    finalize = (
        f"SELECT public.fn_finalize_motion_blind_consensus('{clip}','live',NULL,"
        f"'{id_a}','{id_b}','{dig_a}','{dig_b}','motion-blind-v1','agreed','exclude',NULL,'{{}}');"
    )
    for _ in range(2):
        proc = _psql(dsn, finalize)
        if proc.returncode != 0:
            raise ProbeFailed(f"finalize_failed: {proc.stderr.strip()[:400]}")
    status = _psql(dsn, f"SELECT status FROM public.motion_clip_consensus WHERE clip_id='{clip}' AND cohort_kind='live';")
    if status.stdout.strip() != "agreed":
        raise ProbeFailed(f"consensus_not_agreed: {status.stdout.strip()!r}")
    events = _psql(dsn, f"SELECT count(*) FROM public.motion_clip_consensus_events WHERE clip_id='{clip}' AND event_type='auto_compared';")
    if int((events.stdout or "0").strip() or "0") != 1:
        raise ProbeFailed(f"auto_compared_event_count_not_one: {events.stdout.strip()!r}")


def _psql_argv(dsn: str) -> list[str]:
    return ["docker", "run", "--rm", "-i", "--network", "host", CONTAINER_IMAGE, "psql", dsn, "-v", "ON_ERROR_STOP=1", "-A", "-t"]


def _uuid(seed: str) -> str:
    h = seed.rjust(32, "0")[:32]
    return f"{h[:8]}-{h[8:12]}-4{h[13:16]}-8{h[17:20]}-{h[20:32]}"


def _extract(output: str, prefix: str) -> str:
    for line in output.splitlines():
        line = line.strip()
        if line.startswith(prefix):
            return line[len(prefix):]
    raise ProbeFailed(f"missing marker {prefix!r} in psql output")


# ── setup / submit SQL 템플릿 ────────────────────────────────────────
_SETUP_SQL = """
INSERT INTO auth.users (id) VALUES ('{owner}'), ('{a}'), ('{b}');
INSERT INTO public.labelers (user_id) VALUES ('{a}'), ('{b}');
INSERT INTO public.labeler_applications (user_id, status, display_name)
  VALUES ('{a}','approved','A'), ('{b}','approved','B');
INSERT INTO public.cameras (id, name) VALUES ('{cam}', 'probe-cam');
INSERT INTO public.motion_clips (id, camera_id, started_at, duration_sec, r2_key)
  VALUES ('{clip}', '{cam}', now(), 30, 'probe/clip.mp4');
SELECT public.fn_manage_motion_review_group(NULL, '{owner}', 'probe-group',
  ARRAY['{a}','{b}']::uuid[], ARRAY['{cam}']::uuid[]);
SELECT public.fn_ensure_motion_review_slots('{a}',
  (now() AT TIME ZONE 'Asia/Seoul' - interval '7 hours')::date);
SELECT public.fn_claim_motion_review_slot('{clip}','{a}','live',NULL,'{tok_a}');
SELECT public.fn_claim_motion_review_slot('{clip}','{b}','live',NULL,'{tok_b}');
"""

_SUBMIT_SQL = """
BEGIN;
SELECT 'PEER_{tag}=' || (public.fn_submit_motion_blind_review(
  '{clip}','{reviewer}','live',NULL,'exclude','gecko_absent',NULL,NULL,'{token}')).peer_present::text;
SELECT pg_sleep({sleep});
COMMIT;
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="이중 블라인드 DB 동시성 실증 러너")
    parser.add_argument("--migration", required=True, type=Path)
    parser.add_argument("--prerequisites", required=True, type=Path)
    parser.add_argument("--probe", required=True, type=Path)
    args = parser.parse_args(argv)
    for path in (args.migration, args.prerequisites, args.probe):
        if not path.is_file():
            print(f"{BLOCKED_VERDICT}: missing_file:{path}", file=sys.stderr)
            return 2
    try:
        return run_concurrency_probe(args.migration, args.prerequisites, args.probe)
    except ProbeBlocked as exc:
        print(f"{BLOCKED_VERDICT}: {exc}", file=sys.stderr)
        return 2
    except ProbeFailed as exc:
        print(f"CONCURRENCY_FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
