"""Disposable PostgreSQL 동시 제출 실증 러너 (이중 블라인드 하드닝 Task 6).

정적 SQL 텍스트 테스트만으로 정상 동작을 주장하지 않는다. 최소 prerequisite schema 를 적용한
일회용 PostgreSQL 대상에서:

  (1) rollback probe(hardening_probe.sql) 로 aggregate 실행·live ownership·cross-object
      identity·event idempotency·canary eligibility 를 한 트랜잭션 안에서 검증하고 전량 ROLLBACK
      → DB_RUNTIME_PROBE_OK, 이후 잔여 synthetic row 0 → PROBE_RESIDUE=0
  (2) 두 psql 세션을 실제 동시에 열어 같은 clip×cohort 제출 경합을 재현 → 두 immutable 제출이 모두
      보존되고 peer_present 다중집합이 {false, true}, finalize 후 auto_compared event 는 정확히 1,
      동일 finalize 재시도에도 1 → DB_CONCURRENCY_PROBE_OK

두 backend 를 지원한다(운영 DB 접속 금지, 127.0.0.1/localhost 만):
  - docker: 일회용 postgres:15 컨테이너를 127.0.0.1 에만 바인딩(이미지 없으면 BLOCKED, 임의 pull 안 함).
  - local:  로컬 Homebrew PostgreSQL 에 무작위 `blind_probe_*` 임시 DB 만 createdb → finally 에서 그 DB 만
            dropdb. 기존 DB(postgres/template* 등)는 절대 수정하지 않는다(이름 prefix 검증으로 강제).

Docker/이미지/local 툴 부재는 모두 BLOCKED(READY 주장 금지)로 멈춘다. 이 파일은 임의로 production
migration 을 적용하지 않는다 — 대상은 오직 일회용 컨테이너/임시 DB.
"""

from __future__ import annotations

import argparse
import re
import secrets
import shutil
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
# psql/createdb/dropdb 를 PATH 에서 못 찾을 때 확인하는 Homebrew 기본 위치.
_PG_FALLBACK_DIRS = (
    "/opt/homebrew/opt/postgresql@15/bin",
    "/opt/homebrew/bin",
    "/usr/local/opt/postgresql@15/bin",
    "/usr/local/bin",
)


class ProbeBlocked(Exception):
    """Docker/이미지/local 툴 부재 등으로 실증을 진행할 수 없는 상태. READY 주장 금지 신호."""


class ProbeFailed(Exception):
    """실증은 돌았으나 불변식(동시성/마커/잔여물)이 깨진 상태."""


@dataclass(frozen=True)
class ProbeResult:
    verdict: str
    peer_present: tuple[bool, ...]


# ── 순수 로직(단위 테스트 대상) ──────────────────────────────────────
def validate_database_url(url: str) -> None:
    """DATABASE_URL 이 로컬 일회용 대상만 가리키는지 강제한다(운영 DB 접속 차단)."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if host not in LOCAL_HOSTS:
        raise ProbeBlocked(f"non_local_database_forbidden: host={host!r}")


def temp_database_name(token: str) -> str:
    """무작위 임시 DB 이름. 항상 `blind_probe_` prefix 를 붙여 drop 대상을 좁힌다."""
    return f"blind_probe_{token}"


def validate_temp_database_name(name: str) -> None:
    """create/drop 대상이 `blind_probe_<hex>` 형태인지 강제한다(운영 DB 오삭제 방지)."""
    if not re.fullmatch(r"blind_probe_[a-z0-9]+", name):
        raise ProbeBlocked(f"unsafe_temp_database_name: {name!r}")


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


def _run(cmd: list[str], *, timeout: float = 60.0, input_text: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, input=input_text)


# ── backend 추상화 ───────────────────────────────────────────────────
# 각 backend 는 psql_run(sql)/psql_argv() 만 제공하면 되고, 실증 단계는 공유한다.
_PSQL_FLAGS = ["-v", "ON_ERROR_STOP=1", "-A", "-t", "-q"]


class DockerBackend:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    def _base(self) -> list[str]:
        return ["docker", "run", "--rm", "-i", "--network", "host", CONTAINER_IMAGE, "psql", self.dsn]

    def psql_run(self, sql: str, *, timeout: float = 60.0) -> subprocess.CompletedProcess:
        return _run(self._base() + _PSQL_FLAGS, timeout=timeout, input_text=sql)

    def psql_argv(self) -> list[str]:
        return self._base() + _PSQL_FLAGS


class LocalPostgresBackend:
    def __init__(self, psql: str, dsn: str) -> None:
        self._psql = psql
        self.dsn = dsn

    def psql_run(self, sql: str, *, timeout: float = 60.0) -> subprocess.CompletedProcess:
        return _run([self._psql, self.dsn] + _PSQL_FLAGS, timeout=timeout, input_text=sql)

    def psql_argv(self) -> list[str]:
        return [self._psql, self.dsn] + _PSQL_FLAGS


# ── docker backend 헬퍼 ──────────────────────────────────────────────
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
    proc = _run(["docker", "image", "inspect", CONTAINER_IMAGE], timeout=20)
    if proc.returncode != 0:
        raise ProbeBlocked(f"image_unavailable_needs_approved_download: {CONTAINER_IMAGE}")


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_ready(container: str, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        proc = _run(["docker", "exec", container, "pg_isready", "-U", "postgres", "-h", "127.0.0.1"], timeout=15)
        if proc.returncode == 0:
            return
        time.sleep(1.0)
    raise ProbeBlocked("container_not_ready")


def run_concurrency_probe(migration: Path, prerequisites: Path, probe: Path) -> int:
    """docker backend: 일회용 컨테이너에서 실증. 반환 0=OK,1=FAILED. BLOCKED 는 예외로 전파."""
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
            ["docker", "run", "-d", "--name", container,
             "-e", f"POSTGRES_PASSWORD={password}",
             "-p", f"127.0.0.1:{port}:5432", CONTAINER_IMAGE],
            timeout=60,
        )
        if start.returncode != 0:
            raise ProbeBlocked(f"container_start_failed: {start.stderr.strip()[:200]}")
        started = True
        _wait_ready(container)
        return _run_probe_steps(DockerBackend(dsn), migration, prerequisites, probe)
    finally:
        if started:
            _run(["docker", "rm", "-f", container], timeout=30)
        for leftover in tmpdir.glob("*"):
            leftover.unlink(missing_ok=True)
        tmpdir.rmdir()


# ── local Homebrew postgres backend ──────────────────────────────────
def _find_pg_tool(name: str, pg_bin: str | None) -> str:
    if pg_bin:
        cand = Path(pg_bin) / name
        if cand.is_file():
            return str(cand)
        raise ProbeBlocked(f"pg_tool_missing: {cand}")
    found = shutil.which(name)
    if found:
        return found
    for directory in _PG_FALLBACK_DIRS:
        cand = Path(directory) / name
        if cand.is_file():
            return str(cand)
    raise ProbeBlocked(f"pg_tool_missing: {name}")


# migration 의 REVOKE/GRANT 대상 role. bare postgres 에는 없어 prerequisites 가 IF NOT EXISTS 로 만든다.
_BLIND_ROLES = ("anon", "authenticated", "service_role")


def _existing_blind_roles(backend) -> set[str]:
    proc = backend.psql_run(
        "SELECT rolname FROM pg_roles WHERE rolname IN ('anon','authenticated','service_role');"
    )
    return {ln.strip() for ln in proc.stdout.splitlines() if ln.strip()}


def _drop_created_roles(psql: str, host: str, port: int, roles: list[str]) -> None:
    # 이번 probe 가 새로 만든 role 만(사전 존재분 제외) 정리한다. 이름은 고정 상수라 주입 없음.
    if not roles:
        return
    dsn = f"postgresql://{host}:{port}/postgres"  # temp DB drop 뒤라 postgres 로 접속(내용 수정 없음, 전역 role drop).
    sql = "".join(f"DROP ROLE IF EXISTS {r};" for r in roles if r in _BLIND_ROLES)
    _run([psql, dsn] + _PSQL_FLAGS, timeout=30, input_text=sql)


def run_local_probe(
    migration: Path,
    prerequisites: Path,
    probe: Path,
    *,
    pg_bin: str | None = None,
    host: str = "127.0.0.1",
    port: int = 5432,
) -> int:
    """local backend: 무작위 blind_probe_* 임시 DB 만 만들고 finally 에서 그 DB(+probe 가 만든 전역
    role)만 정리. 기존 DB·기존 role 은 절대 수정/삭제하지 않는다."""
    if host not in LOCAL_HOSTS:
        raise ProbeBlocked(f"non_local_database_forbidden: host={host!r}")
    psql = _find_pg_tool("psql", pg_bin)
    createdb = _find_pg_tool("createdb", pg_bin)
    dropdb = _find_pg_tool("dropdb", pg_bin)

    name = temp_database_name(secrets.token_hex(8))
    validate_temp_database_name(name)  # 생성 전 검증.
    dsn = f"postgresql://{host}:{port}/{name}"
    validate_database_url(dsn)

    created = False
    roles_to_drop: list[str] = []
    try:
        cp = _run([createdb, "-h", host, "-p", str(port), name], timeout=30)
        if cp.returncode != 0:
            raise ProbeBlocked(f"createdb_failed: {cp.stderr.strip()[:300]}")
        created = True
        backend = LocalPostgresBackend(psql, dsn)
        # prerequisites 적용 전 사전 존재 role 을 기록 → probe 가 새로 만든 것만 나중에 정리.
        pre_existing = _existing_blind_roles(backend)
        roles_to_drop = [r for r in _BLIND_ROLES if r not in pre_existing]
        return _run_probe_steps(backend, migration, prerequisites, probe)
    finally:
        if created:
            validate_temp_database_name(name)  # drop 전 재검증(운영 DB 오삭제 방지).
            _run([dropdb, "-h", host, "-p", str(port), "--if-exists", name], timeout=30)
            _drop_created_roles(psql, host, port, roles_to_drop)


# ── backend 공유 실증 단계 ───────────────────────────────────────────
def _run_probe_steps(backend, migration: Path, prerequisites: Path, probe: Path) -> int:
    # 1) prerequisite schema + migration 적용.
    for label, path in (("prerequisites", prerequisites), ("migration", migration)):
        proc = backend.psql_run(path.read_text())
        if proc.returncode != 0:
            raise ProbeFailed(f"{label}_apply_failed: {proc.stderr.strip()[:600]}")

    # 2) rollback runtime probe → DB_RUNTIME_PROBE_OK.
    runtime = backend.psql_run(probe.read_text())
    if runtime.returncode != 0 or "DB_RUNTIME_PROBE_OK" not in runtime.stdout:
        detail = (runtime.stderr.strip() or runtime.stdout.strip())[:600]
        raise ProbeFailed(f"runtime_probe_failed: {detail}")

    # 3) 잔여 synthetic row 0 (rollback probe 뒤, concurrency 전).
    residue = backend.psql_run(
        "SELECT (SELECT count(*) FROM public.motion_clip_review_slots)"
        " + (SELECT count(*) FROM public.motion_clip_blind_submissions)"
        " + (SELECT count(*) FROM public.motion_clip_consensus)"
        " + (SELECT count(*) FROM public.motion_clip_consensus_events);"
    )
    residue_count = int((residue.stdout or "0").strip() or "0")

    # 4) 동시 제출 경합 재현 → DB_CONCURRENCY_PROBE_OK.
    concurrency = _run_concurrency_race(backend)

    print("DB_RUNTIME_PROBE_OK")
    print(concurrency.verdict)
    print(f"PROBE_RESIDUE={residue_count}")
    if concurrency.verdict != "DB_CONCURRENCY_PROBE_OK" or residue_count != 0:
        return 1
    return 0


def _run_concurrency_race(backend) -> ProbeResult:
    """setup → 두 psql 세션 실제 동시 제출 → finalize idempotency 검증."""
    ids = {
        "owner": _uuid(secrets.token_hex(16)),
        "a": _uuid(secrets.token_hex(16)),
        "b": _uuid(secrets.token_hex(16)),
        "cam": _uuid(secrets.token_hex(16)),
        "clip": _uuid(secrets.token_hex(16)),
        "tok_a": _uuid(secrets.token_hex(16)),
        "tok_b": _uuid(secrets.token_hex(16)),
    }
    setup = backend.psql_run(_SETUP_SQL.format(**ids))
    if setup.returncode != 0:
        raise ProbeFailed(f"race_setup_failed: {setup.stderr.strip()[:600]}")

    # A 는 consensus 잠금을 잡고 pg_sleep 하는 동안 유지, B 는 A 커밋까지 대기 → A=false, B=true.
    sql_a = _SUBMIT_SQL.format(clip=ids["clip"], reviewer=ids["a"], token=ids["tok_a"], sleep="1.5", tag="A")
    sql_b = _SUBMIT_SQL.format(clip=ids["clip"], reviewer=ids["b"], token=ids["tok_b"], sleep="0", tag="B")

    proc_a = subprocess.Popen(backend.psql_argv(), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    proc_b = subprocess.Popen(backend.psql_argv(), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        # A 먼저 실행(stdin write+close 로 즉시 시작) → consensus 잠금 확보 + pg_sleep.
        # stdin 을 직접 닫고 None 으로 비워 communicate 가 이미 닫힌 stdin 을 다시 flush 하지 않게 한다
        # (수동 close 후 communicate 는 select 기반 read/wait 만 수행 → pipe deadlock 없이 staggered 실행).
        proc_a.stdin.write(sql_a)
        proc_a.stdin.flush()
        proc_a.stdin.close()
        proc_a.stdin = None
        time.sleep(0.6)  # A 가 consensus 잠금을 확보하도록 여유.
        # 이제 B 를 실행 → submit 이 consensus 잠금에서 A 커밋까지 대기.
        proc_b.stdin.write(sql_b)
        proc_b.stdin.flush()
        proc_b.stdin.close()
        proc_b.stdin = None
        out_a, err_a = proc_a.communicate(timeout=45)
        out_b, err_b = proc_b.communicate(timeout=45)
    except Exception:
        proc_a.kill()
        proc_b.kill()
        raise
    if proc_a.returncode != 0:
        raise ProbeFailed(f"session_a_failed: {err_a.strip()[:400]}")
    if proc_b.returncode != 0:
        raise ProbeFailed(f"session_b_failed: {err_b.strip()[:400]}")

    rows = [
        {"reviewer": "a", "peer_present": _extract(out_a, "PEER_A=")},
        {"reviewer": "b", "peer_present": _extract(out_b, "PEER_B=")},
    ]
    result = parse_probe_rows(rows)

    # 두 immutable 제출 보존 확인.
    count = backend.psql_run(
        f"SELECT count(*) FROM public.motion_clip_blind_submissions WHERE clip_id='{ids['clip']}';"
    )
    if int((count.stdout or "0").strip() or "0") != 2:
        raise ProbeFailed(f"expected exactly two immutable submissions, got {count.stdout.strip()!r}")

    _finalize_and_check(backend, ids["clip"])
    return result


def _finalize_and_check(backend, clip: str) -> None:
    pair = backend.psql_run(
        f"SELECT id || '|' || digest FROM public.motion_clip_blind_submissions "
        f"WHERE clip_id='{clip}' ORDER BY id;"
    )
    lines = [ln for ln in pair.stdout.splitlines() if "|" in ln]
    if len(lines) != 2:
        raise ProbeFailed(f"finalize_pair_lookup_failed: {pair.stdout.strip()!r}")
    (id_a, dig_a), (id_b, dig_b) = (ln.split("|", 1) for ln in lines)
    finalize = (
        f"SELECT public.fn_finalize_motion_blind_consensus('{clip}','live',NULL,"
        f"'{id_a}','{id_b}','{dig_a}','{dig_b}','motion-blind-v1','agreed','exclude',NULL,'{{}}');"
    )
    for _ in range(2):  # 동일 finalize 두 번(멱등) — event 는 여전히 1이어야 한다.
        proc = backend.psql_run(finalize)
        if proc.returncode != 0:
            raise ProbeFailed(f"finalize_failed: {proc.stderr.strip()[:400]}")
    status = backend.psql_run(
        f"SELECT status FROM public.motion_clip_consensus WHERE clip_id='{clip}' AND cohort_kind='live';"
    )
    if status.stdout.strip() != "agreed":
        raise ProbeFailed(f"consensus_not_agreed: {status.stdout.strip()!r}")
    events = backend.psql_run(
        f"SELECT count(*) FROM public.motion_clip_consensus_events "
        f"WHERE clip_id='{clip}' AND event_type='auto_compared';"
    )
    if int((events.stdout or "0").strip() or "0") != 1:
        raise ProbeFailed(f"auto_compared_event_count_not_one: {events.stdout.strip()!r}")


def _uuid(seed: str) -> str:
    h = seed.rjust(32, "0")[:32]
    return f"{h[:8]}-{h[8:12]}-4{h[13:16]}-8{h[17:20]}-{h[20:32]}"


def _extract(output: str, prefix: str) -> str:
    for line in output.splitlines():
        line = line.strip()
        if line.startswith(prefix):
            return line[len(prefix):]
    raise ProbeFailed(f"missing marker {prefix!r} in psql output: {output.strip()[:200]!r}")


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

# SRF 를 FROM 절에서 호출해 정확히 한 번 평가(제출 1건). peer_present 만 뽑는다.
_SUBMIT_SQL = """
BEGIN;
SELECT 'PEER_{tag}=' || peer_present::text
FROM public.fn_submit_motion_blind_review(
  '{clip}','{reviewer}','live',NULL,'exclude','gecko_absent',NULL,NULL,'{token}');
SELECT pg_sleep({sleep});
COMMIT;
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="이중 블라인드 DB 동시성 실증 러너")
    parser.add_argument("--migration", required=True, type=Path)
    parser.add_argument("--prerequisites", required=True, type=Path)
    parser.add_argument("--probe", required=True, type=Path)
    parser.add_argument("--backend", choices=("docker", "local"), default="docker")
    parser.add_argument("--pg-bin", default=None, help="local backend: psql/createdb/dropdb 디렉토리")
    parser.add_argument("--pg-host", default="127.0.0.1", help="local backend host (127.0.0.1/localhost 만)")
    parser.add_argument("--pg-port", default=5432, type=int)
    args = parser.parse_args(argv)
    for path in (args.migration, args.prerequisites, args.probe):
        if not path.is_file():
            print(f"{BLOCKED_VERDICT}: missing_file:{path}", file=sys.stderr)
            return 2
    try:
        if args.backend == "local":
            return run_local_probe(
                args.migration, args.prerequisites, args.probe,
                pg_bin=args.pg_bin, host=args.pg_host, port=args.pg_port,
            )
        return run_concurrency_probe(args.migration, args.prerequisites, args.probe)
    except ProbeBlocked as exc:
        print(f"{BLOCKED_VERDICT}: {exc}", file=sys.stderr)
        return 2
    except ProbeFailed as exc:
        print(f"CONCURRENCY_FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
