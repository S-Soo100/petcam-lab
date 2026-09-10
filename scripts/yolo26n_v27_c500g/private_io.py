"""Deterministic new-only writers for private v2.7 artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import zipfile
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable, Mapping


def canonical_json_bytes(value: object) -> bytes:
    """Serialize one JSON value as deterministic UTF-8 plus a final newline."""
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_private_json_new(path: Path | str, value: Mapping[str, object]) -> None:
    """Create one canonical 0600 JSON artifact and refuse replacement."""
    _write_new(Path(path), canonical_json_bytes(value))


def write_private_zip_new(
    path: Path | str,
    entries: Mapping[str, bytes] | Iterable[tuple[str, bytes]],
) -> None:
    """Create one deterministic 0600 ZIP after validating every entry name."""
    raw_entries = entries.items() if isinstance(entries, Mapping) else entries
    checked: list[tuple[str, bytes]] = []
    seen: set[str] = set()
    for entry in raw_entries:
        if not isinstance(entry, tuple) or len(entry) != 2:
            raise ValueError("ZIP entries must be (name, bytes) pairs")
        name, payload = entry
        _validate_zip_name(name)
        if name in seen:
            raise ValueError(f"duplicate ZIP entry: {name}")
        if not isinstance(payload, bytes):
            raise ValueError(f"ZIP entry payload must be bytes: {name}")
        seen.add(name)
        checked.append((name, payload))

    output = Path(path)

    def write_zip(fd: int) -> None:
        with os.fdopen(os.dup(fd), "wb") as handle:
            with zipfile.ZipFile(handle, "w", compression=zipfile.ZIP_STORED) as archive:
                for name, payload in sorted(checked):
                    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                    info.create_system = 3
                    info.compress_type = zipfile.ZIP_STORED
                    info.external_attr = 0o100600 << 16
                    archive.writestr(info, payload)
            handle.flush()

    _create_private_file(output, write_zip)


def _validate_zip_name(name: object) -> None:
    if not isinstance(name, str) or not name or "\x00" in name or "\\" in name:
        raise ValueError("ZIP entry name must be a non-empty POSIX path")
    if name.endswith("/") or name.startswith("/"):
        raise ValueError(f"ZIP entry name is unsafe: {name}")
    parts = name.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"ZIP entry name is unsafe: {name}")
    path = PurePosixPath(name)
    if path.is_absolute() or path.as_posix() != name or parts[0].endswith(":"):
        raise ValueError(f"ZIP entry name is unsafe: {name}")


def _write_new(path: Path, payload: bytes) -> None:
    def write_payload(fd: int) -> None:
        view = memoryview(payload)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("private artifact write made no progress")
            view = view[written:]

    _create_private_file(path, write_payload)


def _create_private_file(path: Path, writer: Callable[[int], None]) -> None:
    parent_fd, leaf = _prepare_private_target(path)
    fd = -1
    owned = False
    try:
        fd = _open_private_new(parent_fd, leaf)
        owned = True
        os.fchmod(fd, 0o600)
        writer(fd)
        os.fsync(fd)
        os.close(fd)
        fd = -1
        os.fsync(parent_fd)
    except BaseException as error:
        if fd != -1:
            try:
                os.close(fd)
            except OSError as close_error:
                error.add_note(f"private artifact close failed: {close_error}")
        if owned:
            _cleanup_owned_artifact(parent_fd, leaf, error)
        raise
    finally:
        os.close(parent_fd)


def _prepare_private_target(path: Path) -> tuple[int, str]:
    parts = path.parts
    if not parts:
        raise ValueError("private artifact path must not be empty")
    if path.is_absolute():
        parent_fd = _open_directory(path.anchor)
        components = list(parts[1:])
    else:
        parent_fd = _open_directory(".")
        components = list(parts)
    if not components or any(part in {"", ".", ".."} for part in components):
        os.close(parent_fd)
        raise ValueError("private artifact path must use canonical components")

    leaf = components.pop()
    try:
        for index, component in enumerate(components):
            created = False
            try:
                metadata = os.lstat(component, dir_fd=parent_fd)
            except FileNotFoundError:
                os.mkdir(component, 0o700, dir_fd=parent_fd)
                created = True
                metadata = os.lstat(component, dir_fd=parent_fd)
            if stat.S_ISLNK(metadata.st_mode):
                raise ValueError(f"private artifact path contains symlink: {component}")
            if not stat.S_ISDIR(metadata.st_mode):
                raise ValueError(f"private artifact ancestor is not a directory: {component}")
            child_fd = _open_directory(component, dir_fd=parent_fd)
            os.close(parent_fd)
            parent_fd = child_fd
            if created or index == len(components) - 1:
                os.fchmod(parent_fd, 0o700)

        try:
            target_metadata = os.lstat(leaf, dir_fd=parent_fd)
        except FileNotFoundError:
            target_metadata = None
        if target_metadata is not None and stat.S_ISLNK(target_metadata.st_mode):
            raise ValueError(f"private artifact final target is a symlink: {leaf}")
        return parent_fd, leaf
    except BaseException:
        os.close(parent_fd)
        raise


def _open_directory(path: str, *, dir_fd: int | None = None) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    return os.open(path, flags, dir_fd=dir_fd)


def _open_private_new(parent_fd: int, leaf: str) -> int:
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    return os.open(leaf, flags, 0o600, dir_fd=parent_fd)


def _cleanup_owned_artifact(parent_fd: int, leaf: str, original: BaseException) -> None:
    try:
        os.unlink(leaf, dir_fd=parent_fd)
    except OSError as cleanup_error:
        original.add_note(f"private artifact cleanup failed: {cleanup_error}")
        return
    try:
        os.fsync(parent_fd)
    except OSError as sync_error:
        original.add_note(f"private artifact cleanup directory fsync failed: {sync_error}")
