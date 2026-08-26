from pathlib import Path


MIGRATION = Path("migrations/2026-08-26_rap_c500g_recordings.sql")


def sql() -> str:
    return MIGRATION.read_text(encoding="utf-8").lower()


def test_migration_creates_isolated_rls_protected_recording_ledger() -> None:
    source = sql()
    assert "create table public.rap_c500g_recordings" in source
    assert "enable row level security" in source
    assert "revoke all on table public.rap_c500g_recordings from anon, authenticated" in source
    assert "grant all on table public.rap_c500g_recordings to service_role" in source
    assert "unique" in source and "bundle_id" in source


def test_migration_constrains_mode_camera_and_monotonic_status_vocabulary() -> None:
    source = sql()
    assert "mode in ('test', 'production')" in source
    assert "camera_key in ('cam01', 'cam02', 'cam03')" in source
    for status in (
        "capturing",
        "captured",
        "capture_failed",
        "uploading",
        "uploaded",
        "upload_failed",
        "integrity_conflict",
    ):
        assert f"'{status}'" in source
    assert "upload_status <> 'uploaded' or manifest_r2_key is not null" in source


def test_migration_does_not_modify_existing_clip_or_gme_tables() -> None:
    source = sql()
    forbidden = (
        "alter table public.camera_clips",
        "alter table public.motion_clips",
        "alter table public.gme_",
        "update public.camera_clips",
        "update public.motion_clips",
    )
    assert all(fragment not in source for fragment in forbidden)
