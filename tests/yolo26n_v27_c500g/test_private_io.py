from __future__ import annotations

import stat
import zipfile

import pytest

from scripts.yolo26n_v27_c500g import private_io
from scripts.yolo26n_v27_c500g.private_io import (
    sha256_file,
    write_private_json_new,
    write_private_zip_new,
)


def test_private_json_is_canonical_new_0600_and_not_overwritten(tmp_path):
    path = tmp_path / "private/nested/artifact.private.json"
    write_private_json_new(path, {"z": "게코", "a": [2, 1]})

    assert path.read_bytes() == b'{"a":[2,1],"z":"\xea\xb2\x8c\xec\xbd\x94"}\n'
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        write_private_json_new(path, {"schema": "changed"})
    assert path.read_bytes() == b'{"a":[2,1],"z":"\xea\xb2\x8c\xec\xbd\x94"}\n'


def test_private_json_makes_every_new_nested_directory_0700(tmp_path):
    path = tmp_path / "private/level-one/level-two/artifact.json"
    previous_umask = private_io.os.umask(0o022)
    try:
        write_private_json_new(path, {"status": "ok"})
    finally:
        private_io.os.umask(previous_umask)

    assert stat.S_IMODE((tmp_path / "private").stat().st_mode) == 0o700
    assert stat.S_IMODE((tmp_path / "private/level-one").stat().st_mode) == 0o700
    assert stat.S_IMODE((tmp_path / "private/level-one/level-two").stat().st_mode) == 0o700


def test_private_writer_rejects_existing_ancestor_symlink_before_creation(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    private_root = tmp_path / "private"
    private_root.mkdir()
    (private_root / "linked").symlink_to(outside, target_is_directory=True)
    path = private_root / "linked/nested/artifact.json"

    with pytest.raises(ValueError, match="symlink"):
        write_private_json_new(path, {"status": "must-not-write"})

    assert not (outside / "nested/artifact.json").exists()


def test_private_writer_rejects_existing_final_target_symlink(tmp_path):
    outside = tmp_path / "outside.json"
    outside.write_bytes(b"preserve")
    path = tmp_path / "private/artifact.json"
    path.parent.mkdir()
    path.symlink_to(outside)

    with pytest.raises(ValueError, match="symlink"):
        write_private_json_new(path, {"status": "must-not-write"})

    assert outside.read_bytes() == b"preserve"
    assert path.is_symlink()


def test_private_json_removes_partial_artifact_after_write_failure(tmp_path, monkeypatch):
    path = tmp_path / "private/artifact.json"
    real_write = private_io.os.write
    calls = 0

    def fail_after_one_byte(fd, payload):
        nonlocal calls
        calls += 1
        if calls == 1:
            return real_write(fd, payload[:1])
        raise OSError("injected JSON write failure")

    monkeypatch.setattr(private_io.os, "write", fail_after_one_byte)
    with pytest.raises(OSError, match="injected JSON write failure"):
        write_private_json_new(path, {"status": "must-fail"})

    assert not path.exists()


def test_private_zip_removes_partial_artifact_after_archive_failure(tmp_path, monkeypatch):
    path = tmp_path / "private/artifact.zip"

    def fail_writestr(_archive, _info, _payload):
        raise OSError("injected ZIP write failure")

    monkeypatch.setattr(zipfile.ZipFile, "writestr", fail_writestr)
    with pytest.raises(OSError, match="injected ZIP write failure"):
        write_private_zip_new(path, [("image.jpg", b"bytes")])

    assert not path.exists()


def test_private_zip_removes_artifact_after_archive_close_failure(tmp_path, monkeypatch):
    path = tmp_path / "private/artifact.zip"
    real_exit = zipfile.ZipFile.__exit__

    def fail_after_close(archive, exc_type, exc_value, traceback):
        real_exit(archive, exc_type, exc_value, traceback)
        raise OSError("injected ZIP close failure")

    monkeypatch.setattr(zipfile.ZipFile, "__exit__", fail_after_close)
    with pytest.raises(OSError, match="injected ZIP close failure"):
        write_private_zip_new(path, [("image.jpg", b"bytes")])

    assert not path.exists()


def test_private_json_removes_artifact_after_fsync_failure(tmp_path, monkeypatch):
    path = tmp_path / "private/artifact.json"

    def fail_fsync(_fd):
        raise OSError("injected fsync failure")

    monkeypatch.setattr(private_io.os, "fsync", fail_fsync)
    with pytest.raises(OSError, match="injected fsync failure"):
        write_private_json_new(path, {"status": "must-fail"})

    assert not path.exists()


def test_cleanup_failure_preserves_original_error_and_adds_note(tmp_path, monkeypatch):
    path = tmp_path / "private/artifact.json"

    def fail_write(_fd, _payload):
        raise OSError("original write failure")

    def fail_unlink(_path, *, dir_fd=None):
        raise PermissionError("injected cleanup failure")

    monkeypatch.setattr(private_io.os, "write", fail_write)
    monkeypatch.setattr(private_io.os, "unlink", fail_unlink)
    with pytest.raises(OSError, match="original write failure") as caught:
        write_private_json_new(path, {"status": "must-fail"})

    assert any(
        "private artifact cleanup failed" in note
        for note in getattr(caught.value, "__notes__", ())
    )
    assert path.exists()


def test_sha256_file_hashes_exact_file_bytes(tmp_path):
    path = tmp_path / "bytes.bin"
    path.write_bytes(b"abc")
    assert sha256_file(path) == (
        "ba7816bf8f01cfea414140de5dae2223"
        "b00361a396177a9cb410ff61f20015ad"
    )


def test_private_zip_is_deterministic_new_0600_with_private_entries(tmp_path):
    first = tmp_path / "one/review.private.zip"
    second = tmp_path / "two/review.private.zip"
    entries = [("images/V27P0002.jpg", b"two"), ("images/V27P0001.jpg", b"one")]

    write_private_zip_new(first, entries)
    write_private_zip_new(second, reversed(entries))

    assert sha256_file(first) == sha256_file(second)
    assert stat.S_IMODE(first.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(first.stat().st_mode) == 0o600
    with zipfile.ZipFile(first) as archive:
        assert archive.namelist() == ["images/V27P0001.jpg", "images/V27P0002.jpg"]
        assert [archive.read(name) for name in archive.namelist()] == [b"one", b"two"]
        assert all((info.external_attr >> 16) & 0o777 == 0o600 for info in archive.infolist())

    with pytest.raises(FileExistsError):
        write_private_zip_new(first, [("new.txt", b"changed")])


@pytest.mark.parametrize(
    "name",
    [
        "../secret",
        "images/../../secret",
        "/absolute.jpg",
        "images\\windows.jpg",
        "images//double.jpg",
        "./relative.jpg",
        "directory/",
        "",
    ],
)
def test_private_zip_rejects_unsafe_or_noncanonical_entry_names(tmp_path, name):
    with pytest.raises(ValueError, match="ZIP entry"):
        write_private_zip_new(tmp_path / "artifact.zip", [(name, b"x")])
    assert not (tmp_path / "artifact.zip").exists()


def test_private_zip_rejects_duplicate_entry_names_before_creating_output(tmp_path):
    path = tmp_path / "artifact.zip"
    with pytest.raises(ValueError, match="duplicate"):
        write_private_zip_new(path, [("same.jpg", b"one"), ("same.jpg", b"two")])
    assert not path.exists()
