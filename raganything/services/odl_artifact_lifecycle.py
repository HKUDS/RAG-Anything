"""Fail-closed lifecycle management for OpenDataLoader parser artifacts.

This module deliberately owns *only* server-created OpenDataLoader output
directories.  It does not accept a path from document metadata, cache data, or
an upload request as authority to remove files.  An integration must register
the output run after parsing, and later identify it by its immutable KB/document
owner plus an optimistic generation number.

Destructive operations are intentionally available only on Linux runtimes that
offer the descriptor-relative ``O_NOFOLLOW`` primitives used below.  Windows
workers may still parse documents and maintain the registry, but automatic
retry/deletion/retention cleanup fails closed until a separately reviewed
native handle-based implementation is introduced.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import secrets
import sqlite3
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Callable, Iterator


_RUN_RELATIVE_RE = re.compile(
    r"^(?P<stem>[^/\\\x00]{1,128})_"
    r"(?P<hash>[0-9a-f]{8,64})/"
    r"(?P<nonce>run-[A-Za-z0-9][A-Za-z0-9_-]{7,127})$"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TOMBSTONE_RE = re.compile(
    r"^\.odl-artifact-tombstones/[0-9a-f]{64}-g[1-9][0-9]*-[0-9a-f]{32}$"
)
_VALID_STATES = frozenset({"active", "deleting", "deleted"})
_UNSAFE_VOLUME_TYPES = frozenset(
    {
        "9p",
        "aufs",
        "cifs",
        "drvfs",
        "fuse",
        "fuseblk",
        "nfs",
        "nfs4",
        "overlay",
        "smb",
        "smb2",
        "smb3",
        "virtiofs",
    }
)


def _sha256_stream(stream: BinaryIO) -> str:
    digest = hashlib.sha256()
    while chunk := stream.read(1024 * 1024):
        digest.update(chunk)
    return digest.hexdigest()


class ArtifactLifecycleError(RuntimeError):
    """Base class for a lifecycle safety or state-transition failure."""


class ArtifactLifecycleCapabilityError(ArtifactLifecycleError):
    """Raised where automatic artifact deletion is not proven safe."""


class ArtifactRegistryConflict(ArtifactLifecycleError):
    """Raised for stale generation, duplicate ownership, or illegal state."""


class UnsafeArtifactPath(ArtifactLifecycleError):
    """Raised when an artifact path or entry violates the controlled-root ABI."""


def configured_odl_artifact_root() -> Path | None:
    """Return the explicitly configured dedicated artifact root, if any.

    This function deliberately does not derive a root from ``OUTPUT_DIR`` or a
    knowledge-base name.  Doing so would make a shared parser tree eligible for
    lifecycle deletion.
    """
    configured = os.getenv("ODL_ARTIFACT_ROOT", "").strip()
    if not configured:
        return None
    root = Path(configured)
    if not root.is_absolute():
        raise UnsafeArtifactPath("ODL_ARTIFACT_ROOT must be an absolute path")
    return Path(os.path.abspath(root))


@dataclass(frozen=True)
class ArtifactOwner:
    """Immutable logical owner; neither field is a filesystem path."""

    kb_id: str
    doc_id: str

    def __post_init__(self) -> None:
        _validate_owner_component("kb_id", self.kb_id)
        _validate_owner_component("doc_id", self.doc_id)


@dataclass(frozen=True)
class ArtifactRecord:
    """Server-owned record used for generation-checked lifecycle operations."""

    owner: ArtifactOwner
    run_relpath: str
    sidecar_relpath: str
    sidecar_sha256: str
    generation: int
    state: str
    tombstone_relpath: str | None


def _validate_owner_component(name: str, value: str) -> None:
    if not isinstance(value, str) or not value or len(value) > 512 or "\x00" in value:
        raise ValueError(f"{name} must be a non-empty identifier without NUL bytes")


def validate_run_relative_path(run_relpath: str) -> str:
    """Validate the only on-disk run layout accepted by the registry.

    The adapter's collision-avoidance ABI is ``stem_hash/run-nonce``.  A
    normalised relative path alone is not sufficient: accepting ``.``, extra
    components, Windows separators, or arbitrary legacy output names would
    make a metadata value capable of widening deletion scope.
    """

    matched = (
        _RUN_RELATIVE_RE.fullmatch(run_relpath)
        if isinstance(run_relpath, str)
        else None
    )
    if matched is None:
        raise UnsafeArtifactPath("artifact run path must be strict stem_hash/run-nonce")
    if not _is_safe_single_component(matched.group("stem")):
        raise UnsafeArtifactPath("artifact run path must be a portable relative path")
    return run_relpath


def _is_safe_single_component(value: str) -> bool:
    return (
        bool(value)
        and value not in {".", ".."}
        and "/" not in value
        and "\\" not in value
        and "\x00" not in value
        and not any(ord(character) < 32 for character in value)
    )


def _validate_sidecar_hash(sidecar_sha256: str) -> str:
    if not isinstance(sidecar_sha256, str) or not _SHA256_RE.fullmatch(sidecar_sha256):
        raise ValueError("sidecar_sha256 must be a lowercase SHA-256 digest")
    return sidecar_sha256


def _has_reparse_point(file_stat: os.stat_result) -> bool:
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    # ``st_file_attributes`` exists only on Windows.  A Linux ``stat_result``
    # must be treated as having no reparse-point attribute rather than raising
    # while validating a controlled volume.
    return bool(reparse and getattr(file_stat, "st_file_attributes", 0) & reparse)


def _is_linux_fd_safe() -> bool:
    """Return whether host primitives meet the deletion safety contract."""

    required = (os.open, os.stat, os.unlink, os.rmdir, os.rename)
    supports_dir_fd = getattr(os, "supports_dir_fd", set())
    supports_follow_symlinks = getattr(os, "supports_follow_symlinks", set())
    return (
        sys.platform.startswith("linux")
        and hasattr(os, "O_NOFOLLOW")
        and hasattr(os, "O_DIRECTORY")
        and all(operation in supports_dir_fd for operation in required)
        and os.stat in supports_follow_symlinks
    )


def _unescape_mountinfo(value: str) -> str:
    """Decode the octal escapes used by Linux ``/proc/*/mountinfo``."""

    return re.sub(
        r"\\([0-7]{3})",
        lambda match: chr(int(match.group(1), 8)),
        value,
    )


def _linux_mount_filesystem(path: Path) -> str:
    """Return the filesystem type of the deepest Linux mount containing path."""

    try:
        lines = Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ArtifactLifecycleCapabilityError(
            "cannot inspect Linux mount metadata for the controlled artifact volume"
        ) from exc
    normalized = str(path)
    candidates: list[tuple[int, str]] = []
    for line in lines:
        try:
            before, after = line.split(" - ", 1)
            before_fields = before.split()
            after_fields = after.split()
            mountpoint = _unescape_mountinfo(before_fields[4])
            filesystem = after_fields[0].lower()
        except (IndexError, ValueError):
            continue
        if normalized == mountpoint or normalized.startswith(mountpoint.rstrip("/") + "/"):
            candidates.append((len(mountpoint), filesystem))
    if not candidates:
        raise ArtifactLifecycleCapabilityError(
            "cannot determine the filesystem of the controlled artifact volume"
        )
    return max(candidates, key=lambda item: item[0])[1]


class OpenDataLoaderArtifactLifecycle:
    """SQLite-backed ownership registry and secure Linux artifact reaper.

    ``artifact_root`` is a provisioned, dedicated directory on a controlled
    Linux/Docker/WSL volume.  It must not be a parser's shared parent or an
    arbitrary working directory.  The registry intentionally lives at the
    root level, while registered runs always have exactly two child components,
    preventing a lifecycle call from targeting registry/lock infrastructure.
    """

    _REGISTRY_FILE = ".odl-artifact-registry.sqlite3"
    _LOCK_DIR = ".odl-artifact-locks"
    _TOMBSTONE_DIR = ".odl-artifact-tombstones"

    def __init__(self, artifact_root: str | os.PathLike[str]) -> None:
        root = Path(os.path.abspath(os.fspath(artifact_root)))
        self._assert_existing_directory_not_link(root, label="artifact root")
        self.artifact_root = root
        self._registry_path = root / self._REGISTRY_FILE
        self._ensure_registry()

    @staticmethod
    def destructive_operations_supported() -> bool:
        """Expose the host capability gate for operator health checks."""

        return _is_linux_fd_safe()

    def register(
        self,
        owner: ArtifactOwner,
        *,
        run_relpath: str,
        sidecar_relpath: str,
        sidecar_sha256: str,
        expected_generation: int | None = None,
    ) -> ArtifactRecord:
        """Atomically bind a completed, validated run to an owner.

        A new owner starts at generation one.  A retry can register only after
        the prior generation reached ``deleted`` and must present that prior
        generation.  This prevents a second active run from being attached to
        an owner or an active run from being stolen by another owner.
        """

        run_relpath = validate_run_relative_path(run_relpath)
        self._validate_sidecar_relative_path(run_relpath, sidecar_relpath)
        sidecar_sha256 = _validate_sidecar_hash(sidecar_sha256)
        self._assert_registered_run_is_safe_directory(run_relpath)
        self._assert_sidecar_matches(run_relpath, sidecar_relpath, sidecar_sha256)

        with self._owner_lock(owner):
            with self._transaction() as connection:
                existing = self._select_record(connection, owner)
                conflicting = connection.execute(
                    "SELECT kb_id, doc_id FROM odl_artifact_runs WHERE run_relpath = ?",
                    (run_relpath,),
                ).fetchone()
                if conflicting and (
                    conflicting["kb_id"] != owner.kb_id
                    or conflicting["doc_id"] != owner.doc_id
                ):
                    raise ArtifactRegistryConflict(
                        "a parser run is already bound to a different owner"
                    )

                if existing is None:
                    if expected_generation is not None:
                        raise ArtifactRegistryConflict("new owner cannot specify a generation")
                    generation = 1
                    connection.execute(
                        """
                        INSERT INTO odl_artifact_runs
                            (kb_id, doc_id, run_relpath, sidecar_relpath, sidecar_sha256, generation, state)
                        VALUES (?, ?, ?, ?, ?, ?, 'active')
                        """,
                        (
                            owner.kb_id,
                            owner.doc_id,
                            run_relpath,
                            sidecar_relpath,
                            sidecar_sha256,
                            generation,
                        ),
                    )
                else:
                    if expected_generation is None or existing.generation != expected_generation:
                        raise ArtifactRegistryConflict("artifact generation compare-and-swap failed")
                    if existing.state != "deleted":
                        raise ArtifactRegistryConflict(
                            "previous artifact generation must be deleted before retry registration"
                        )
                    generation = existing.generation + 1
                    updated = connection.execute(
                        """
                        UPDATE odl_artifact_runs
                        SET run_relpath=?, sidecar_relpath=?, sidecar_sha256=?, generation=?, state='active',
                            tombstone_relpath=NULL, updated_at=CURRENT_TIMESTAMP
                        WHERE kb_id=? AND doc_id=? AND generation=? AND state='deleted'
                        """,
                        (
                            run_relpath,
                            sidecar_relpath,
                            sidecar_sha256,
                            generation,
                            owner.kb_id,
                            owner.doc_id,
                            expected_generation,
                        ),
                    ).rowcount
                    if updated != 1:
                        raise ArtifactRegistryConflict("artifact generation compare-and-swap failed")
                return ArtifactRecord(
                    owner=owner,
                    run_relpath=run_relpath,
                    sidecar_relpath=sidecar_relpath,
                    sidecar_sha256=sidecar_sha256,
                    generation=generation,
                    state="active",
                    tombstone_relpath=None,
                )

    def get(self, owner: ArtifactOwner) -> ArtifactRecord | None:
        """Return server registry state; it never reconstructs state from paths."""

        with self._connect() as connection:
            return self._select_record(connection, owner)

    def list_records_for_kb(
        self, kb_id: str, *, states: set[str] | None = None
    ) -> list[ArtifactRecord]:
        """List server registry entries for a KB; no filesystem discovery occurs."""

        _validate_owner_component("kb_id", kb_id)
        if states is not None and not states.issubset(_VALID_STATES):
            raise ValueError("states must contain only active, deleting, or deleted")
        query = "SELECT * FROM odl_artifact_runs WHERE kb_id=?"
        args: list[object] = [kb_id]
        if states is not None:
            if not states:
                return []
            placeholders = ",".join("?" for _ in states)
            query += f" AND state IN ({placeholders})"
            args.extend(sorted(states))
        query += " ORDER BY doc_id"
        with self._connect() as connection:
            rows = connection.execute(query, args).fetchall()
        return [self._row_to_record(row) for row in rows]

    def delete_kb(
        self, kb_id: str, *, worker_exited: Callable[[ArtifactOwner], bool]
    ) -> list[ArtifactRecord]:
        """Delete only registry-bound runs for a KB after each worker exits.

        This intentionally does not recurse over a KB directory and does not
        accept a collection of paths from metadata.  A crash leaves a durable
        ``deleting`` tombstone that :meth:`recover_deletions` can later resume.
        """

        self._require_destructive_capability()
        _validate_owner_component("kb_id", kb_id)
        if not callable(worker_exited):
            raise TypeError("worker_exited must be an owner-to-bool callable")
        removed: list[ArtifactRecord] = []
        for listed in self.list_records_for_kb(kb_id, states={"active", "deleting"}):
            with self._owner_lock(listed.owner):
                current = self.get(listed.owner)
                if current is None or current.state == "deleted":
                    continue
                if current.generation != listed.generation:
                    raise ArtifactRegistryConflict(
                        "artifact generation changed during KB deletion"
                    )
                if worker_exited(current.owner) is not True:
                    raise ArtifactLifecycleError(
                        "refusing KB deletion until every owning worker has exited"
                    )
                if current.state == "active":
                    current = self._transition_to_deleting(
                        current.owner, current.generation
                    )
                removed.append(self._remove_or_recover_deleting_record(current))
        return removed

    def purge_deleted_registry_records(self, *, kb_id: str | None = None) -> int:
        """Optionally prune only records already proven filesystem-deleted.

        This is a registry-retention operation, not artifact cleanup.  It can
        never delete active output and is useful only after external audit
        retention for the tombstone record has elapsed.
        """

        if kb_id is not None:
            _validate_owner_component("kb_id", kb_id)
        deleted_records = self.list_records_for_kb(
            kb_id, states={"deleted"}
        ) if kb_id is not None else self._list_deleted_records()
        purged = 0
        for record in deleted_records:
            with self._owner_lock(record.owner):
                with self._transaction() as connection:
                    result = connection.execute(
                        """
                        DELETE FROM odl_artifact_runs
                        WHERE kb_id=? AND doc_id=? AND generation=? AND state='deleted'
                        """,
                        (
                            record.owner.kb_id,
                            record.owner.doc_id,
                            record.generation,
                        ),
                    )
                    purged += result.rowcount
        return purged

    def delete(
        self,
        owner: ArtifactOwner,
        *,
        expected_generation: int,
        worker_exited: bool,
    ) -> ArtifactRecord:
        """Tombstone and remove one active run, failing closed on any uncertainty."""

        self._require_destructive_capability()
        if worker_exited is not True:
            raise ArtifactLifecycleError("refusing deletion until the owning worker has exited")
        if not isinstance(expected_generation, int) or expected_generation < 1:
            raise ValueError("expected_generation must be a positive integer")

        with self._owner_lock(owner):
            record = self._transition_to_deleting(owner, expected_generation)
            return self._remove_or_recover_deleting_record(record)

    def recover_deletions(
        self, *, worker_exited: Callable[[ArtifactOwner], bool]
    ) -> list[ArtifactRecord]:
        """Resume persisted tombstones after a crash, subject to worker confirmation."""

        self._require_destructive_capability()
        if not callable(worker_exited):
            raise TypeError("worker_exited must be an owner-to-bool callable")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM odl_artifact_runs WHERE state='deleting' ORDER BY kb_id, doc_id"
            ).fetchall()
        recovered: list[ArtifactRecord] = []
        for row in rows:
            record = self._row_to_record(row)
            with self._owner_lock(record.owner):
                current = self.get(record.owner)
                if current is None or current.state != "deleting":
                    continue
                if current.generation != record.generation:
                    continue
                if worker_exited(current.owner) is not True:
                    raise ArtifactLifecycleError(
                        "refusing tombstone recovery until the owning worker has exited"
                    )
                recovered.append(self._remove_or_recover_deleting_record(current))
        return recovered

    def _transition_to_deleting(
        self, owner: ArtifactOwner, expected_generation: int
    ) -> ArtifactRecord:
        with self._transaction() as connection:
            current = self._select_record(connection, owner)
            if current is None:
                raise ArtifactRegistryConflict("no artifact registry entry for owner")
            if current.generation != expected_generation or current.state != "active":
                raise ArtifactRegistryConflict("artifact generation compare-and-swap failed")
            tombstone = self._new_tombstone_relpath(owner, current.generation)
            updated = connection.execute(
                """
                UPDATE odl_artifact_runs
                SET state='deleting', tombstone_relpath=?, updated_at=CURRENT_TIMESTAMP
                WHERE kb_id=? AND doc_id=? AND generation=? AND state='active'
                """,
                (tombstone, owner.kb_id, owner.doc_id, expected_generation),
            ).rowcount
            if updated != 1:
                raise ArtifactRegistryConflict("artifact generation compare-and-swap failed")
            return ArtifactRecord(
                owner=owner,
                run_relpath=current.run_relpath,
                sidecar_relpath=current.sidecar_relpath,
                sidecar_sha256=current.sidecar_sha256,
                generation=current.generation,
                state="deleting",
                tombstone_relpath=tombstone,
            )

    def _remove_or_recover_deleting_record(self, record: ArtifactRecord) -> ArtifactRecord:
        if record.state != "deleting" or not record.tombstone_relpath:
            raise ArtifactRegistryConflict("only a persisted deleting record may be removed")
        self._validate_tombstone_relative_path(record.tombstone_relpath)
        with self._open_root_fd() as root_fd:
            source_exists = self._run_exists_at(root_fd, record.run_relpath)
            tombstone_exists = self._tombstone_exists_at(root_fd, record.tombstone_relpath)
            if source_exists and tombstone_exists:
                raise UnsafeArtifactPath("both active and tombstone artifact directories exist")
            if source_exists:
                self._rename_run_to_tombstone(root_fd, record.run_relpath, record.tombstone_relpath)
                tombstone_exists = True
            if tombstone_exists:
                self._remove_tombstone_tree(root_fd, record.tombstone_relpath)
        return self._mark_deleted(record)

    def _mark_deleted(self, record: ArtifactRecord) -> ArtifactRecord:
        with self._transaction() as connection:
            updated = connection.execute(
                """
                UPDATE odl_artifact_runs
                SET state='deleted', updated_at=CURRENT_TIMESTAMP
                WHERE kb_id=? AND doc_id=? AND generation=? AND state='deleting'
                    AND tombstone_relpath=?
                """,
                (
                    record.owner.kb_id,
                    record.owner.doc_id,
                    record.generation,
                    record.tombstone_relpath,
                ),
            ).rowcount
            if updated != 1:
                raise ArtifactRegistryConflict("artifact deletion state changed concurrently")
        return ArtifactRecord(
            owner=record.owner,
            run_relpath=record.run_relpath,
            sidecar_relpath=record.sidecar_relpath,
            sidecar_sha256=record.sidecar_sha256,
            generation=record.generation,
            state="deleted",
            tombstone_relpath=record.tombstone_relpath,
        )

    def _assert_registered_run_is_safe_directory(self, run_relpath: str) -> None:
        """Reject link/reparse directories before a path can become registry state."""

        parts = run_relpath.split("/")
        candidate = self.artifact_root / parts[0] / parts[1]
        try:
            parent_stat = (self.artifact_root / parts[0]).lstat()
            run_stat = candidate.lstat()
        except FileNotFoundError as exc:
            raise UnsafeArtifactPath("registered artifact run directory does not exist") from exc
        if (
            _has_reparse_point(parent_stat)
            or _has_reparse_point(run_stat)
            or stat.S_ISLNK(parent_stat.st_mode)
            or stat.S_ISLNK(run_stat.st_mode)
            or not stat.S_ISDIR(parent_stat.st_mode)
            or not stat.S_ISDIR(run_stat.st_mode)
        ):
            raise UnsafeArtifactPath("registered artifact run must be a real directory")

    def _assert_sidecar_matches(
        self, run_relpath: str, sidecar_relpath: str, expected_sha256: str
    ) -> None:
        """Bind registry state to an actual in-run sidecar, never an external path."""

        sidecar_name = self._validate_sidecar_relative_path(run_relpath, sidecar_relpath)
        candidate = self.artifact_root.joinpath(*run_relpath.split("/"), sidecar_name)
        try:
            sidecar_stat = candidate.lstat()
        except FileNotFoundError as exc:
            raise UnsafeArtifactPath("registered provenance sidecar does not exist") from exc
        if (
            not stat.S_ISREG(sidecar_stat.st_mode)
            or stat.S_ISLNK(sidecar_stat.st_mode)
            or _has_reparse_point(sidecar_stat)
            or sidecar_stat.st_nlink != 1
        ):
            raise UnsafeArtifactPath("registered provenance sidecar must be a regular file")

        # On the approved Linux volume, hash through an O_NOFOLLOW descriptor
        # and confirm inode identity before recording it.  On Windows this is
        # non-destructive validation only; cleanup still fails closed.
        if _is_linux_fd_safe():
            with self._open_root_fd() as root_fd:
                parent_name, run_name = self._split_run(run_relpath)
                parent_fd = os.open(
                    parent_name,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=root_fd,
                )
                try:
                    run_fd = os.open(
                        run_name,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                        dir_fd=parent_fd,
                    )
                    try:
                        self._hash_sidecar_fd(run_fd, sidecar_name, sidecar_stat, expected_sha256)
                    finally:
                        os.close(run_fd)
                finally:
                    os.close(parent_fd)
            return
        with candidate.open("rb") as sidecar_file:
            actual_sha256 = _sha256_stream(sidecar_file)
        if actual_sha256 != expected_sha256:
            raise UnsafeArtifactPath("provenance sidecar hash does not match registry input")

    @staticmethod
    def _validate_sidecar_relative_path(run_relpath: str, sidecar_relpath: str) -> str:
        if not isinstance(sidecar_relpath, str) or "\\" in sidecar_relpath:
            raise UnsafeArtifactPath("sidecar path must be a portable relative path")
        required_prefix = f"{run_relpath}/"
        if not sidecar_relpath.startswith(required_prefix):
            raise UnsafeArtifactPath("sidecar must be a direct child of its registered run")
        sidecar_name = sidecar_relpath[len(required_prefix) :]
        if len(sidecar_name) > 255 or not _is_safe_single_component(sidecar_name):
            raise UnsafeArtifactPath("sidecar name violates the controlled-run ABI")
        return sidecar_name

    @staticmethod
    def _hash_sidecar_fd(
        run_fd: int,
        sidecar_name: str,
        expected_stat: os.stat_result,
        expected_sha256: str,
    ) -> None:
        fd = os.open(sidecar_name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=run_fd)
        try:
            opened_stat = os.fstat(fd)
            if (
                not stat.S_ISREG(opened_stat.st_mode)
                or opened_stat.st_nlink != 1
                or opened_stat.st_dev != expected_stat.st_dev
                or opened_stat.st_ino != expected_stat.st_ino
            ):
                raise UnsafeArtifactPath("provenance sidecar changed during validation")
            with os.fdopen(fd, "rb", closefd=False) as sidecar_file:
                actual_sha256 = _sha256_stream(sidecar_file)
            if actual_sha256 != expected_sha256:
                raise UnsafeArtifactPath("provenance sidecar hash does not match registry input")
        finally:
            os.close(fd)

    def _assert_existing_directory_not_link(self, path: Path, *, label: str) -> None:
        # The controlled-volume guarantee includes every ancestor.  Checking
        # only the final component would still allow a parent mount/junction to
        # be substituted between registry construction and fd-relative work.
        current = path
        while True:
            try:
                file_stat = current.lstat()
            except FileNotFoundError as exc:
                raise UnsafeArtifactPath(
                    f"{label} and all of its ancestors must be provisioned before use"
                ) from exc
            if (
                not stat.S_ISDIR(file_stat.st_mode)
                or stat.S_ISLNK(file_stat.st_mode)
                or _has_reparse_point(file_stat)
            ):
                raise UnsafeArtifactPath(
                    f"{label} and its ancestors must be real directories, not links"
                )
            if current.parent == current:
                return
            current = current.parent

    def _ensure_registry(self) -> None:
        try:
            registry_fd = os.open(
                self._registry_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
        except FileExistsError:
            pass
        else:
            os.close(registry_fd)
        self._assert_secure_registry_file(require_owner=False)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS odl_artifact_runs (
                    kb_id TEXT NOT NULL,
                    doc_id TEXT NOT NULL,
                    run_relpath TEXT NOT NULL UNIQUE,
                    sidecar_relpath TEXT NOT NULL,
                    sidecar_sha256 TEXT NOT NULL,
                    generation INTEGER NOT NULL CHECK(generation > 0),
                    state TEXT NOT NULL CHECK(state IN ('active', 'deleting', 'deleted')),
                    tombstone_relpath TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (kb_id, doc_id)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_odl_artifact_deleting "
                "ON odl_artifact_runs(state) WHERE state='deleting'"
            )

    def _connect(self) -> sqlite3.Connection:
        self._assert_secure_registry_file(require_owner=False)
        connection = sqlite3.connect(self._registry_path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    @contextlib.contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    @contextlib.contextmanager
    def _owner_lock(self, owner: ArtifactOwner) -> Iterator[None]:
        """Use a per-owner cross-process Linux lock in addition to SQLite CAS."""

        if not _is_linux_fd_safe():
            # SQLite BEGIN IMMEDIATE still serializes registry writes.  This
            # branch intentionally never authorizes destructive filesystem work.
            yield
            return
        import fcntl  # Linux-only; delayed to keep default Windows imports safe.

        owner_hash = hashlib.sha256(
            f"{owner.kb_id}\x00{owner.doc_id}".encode("utf-8")
        ).hexdigest()
        with self._open_root_fd() as root_fd:
            lock_dir_fd = self._ensure_control_directory(root_fd, self._LOCK_DIR)
            try:
                lock_fd = os.open(
                    f"{owner_hash}.lock",
                    os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=lock_dir_fd,
                )
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_EX)
                    yield
                finally:
                    os.close(lock_fd)
            finally:
                os.close(lock_dir_fd)

    @contextlib.contextmanager
    def _open_root_fd(self) -> Iterator[int]:
        expected_root_identity = self._require_destructive_capability()
        root_fd = os.open(
            self.artifact_root,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
        )
        try:
            opened_root = os.fstat(root_fd)
            if (
                not stat.S_ISDIR(opened_root.st_mode)
                or (opened_root.st_dev, opened_root.st_ino) != expected_root_identity
                or opened_root.st_uid != os.geteuid()
                or opened_root.st_mode & (stat.S_IRWXG | stat.S_IRWXO)
            ):
                raise ArtifactLifecycleCapabilityError(
                    "controlled artifact root changed or lost its private service-owned identity"
                )
            yield root_fd
        finally:
            os.close(root_fd)

    def _require_destructive_capability(self) -> tuple[int, int]:
        """Validate the root and return the identity the fd opener must match."""
        if not _is_linux_fd_safe():
            raise ArtifactLifecycleCapabilityError(
                "automatic OpenDataLoader artifact deletion is supported only on "
                "Linux/Docker/WSL with fd-relative O_NOFOLLOW primitives; this "
                "runtime must retain artifacts for administrator-controlled cleanup"
            )
        if os.getenv("ODL_ARTIFACT_CLEANUP_MODE") != "linux-volume":
            raise ArtifactLifecycleCapabilityError(
                "automatic OpenDataLoader artifact deletion requires explicit "
                "ODL_ARTIFACT_CLEANUP_MODE=linux-volume approval for the controlled volume"
            )
        filesystem = _linux_mount_filesystem(self.artifact_root)
        if filesystem in _UNSAFE_VOLUME_TYPES:
            raise ArtifactLifecycleCapabilityError(
                "automatic OpenDataLoader artifact deletion requires a local Linux "
                f"volume, not filesystem type {filesystem!r}"
            )
        root_stat = self.artifact_root.stat()
        if root_stat.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise ArtifactLifecycleCapabilityError(
                "controlled artifact root must not be writable by group or other users"
            )
        if root_stat.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
            raise ArtifactLifecycleCapabilityError(
                "controlled artifact root must be private to the worker service identity"
            )
        if root_stat.st_uid != os.geteuid():
            raise ArtifactLifecycleCapabilityError(
                "controlled artifact root must be owned by the worker service identity"
            )
        self._assert_secure_registry_file(require_owner=True)
        return root_stat.st_dev, root_stat.st_ino

    def _assert_secure_registry_file(self, *, require_owner: bool) -> None:
        """Reject a registry that is not a private, regular server-owned file."""
        try:
            registry_stat = self._registry_path.lstat()
        except FileNotFoundError as exc:
            raise UnsafeArtifactPath("artifact registry is missing") from exc
        if (
            not stat.S_ISREG(registry_stat.st_mode)
            or stat.S_ISLNK(registry_stat.st_mode)
            or _has_reparse_point(registry_stat)
            or registry_stat.st_nlink != 1
        ):
            raise UnsafeArtifactPath("artifact registry must be an unlinked regular file")
        if require_owner:
            if registry_stat.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
                raise ArtifactLifecycleCapabilityError(
                    "artifact registry must not grant group or other permissions"
                )
            if registry_stat.st_uid != os.geteuid():
                raise ArtifactLifecycleCapabilityError(
                    "artifact registry must be owned by the worker service identity"
                )

    @staticmethod
    def _select_record(
        connection: sqlite3.Connection, owner: ArtifactOwner
    ) -> ArtifactRecord | None:
        row = connection.execute(
            "SELECT * FROM odl_artifact_runs WHERE kb_id=? AND doc_id=?",
            (owner.kb_id, owner.doc_id),
        ).fetchone()
        return None if row is None else OpenDataLoaderArtifactLifecycle._row_to_record(row)

    def _list_deleted_records(self) -> list[ArtifactRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM odl_artifact_runs WHERE state='deleted' ORDER BY kb_id, doc_id"
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> ArtifactRecord:
        state = str(row["state"])
        if state not in _VALID_STATES:
            raise ArtifactRegistryConflict("registry contains an invalid artifact state")
        return ArtifactRecord(
            owner=ArtifactOwner(str(row["kb_id"]), str(row["doc_id"])),
            run_relpath=validate_run_relative_path(str(row["run_relpath"])),
            sidecar_relpath=OpenDataLoaderArtifactLifecycle._record_sidecar_path(row),
            sidecar_sha256=_validate_sidecar_hash(str(row["sidecar_sha256"])),
            generation=int(row["generation"]),
            state=state,
            tombstone_relpath=(
                None if row["tombstone_relpath"] is None else str(row["tombstone_relpath"])
            ),
        )

    @staticmethod
    def _record_sidecar_path(row: sqlite3.Row) -> str:
        run_relpath = validate_run_relative_path(str(row["run_relpath"]))
        sidecar_relpath = str(row["sidecar_relpath"])
        OpenDataLoaderArtifactLifecycle._validate_sidecar_relative_path(
            run_relpath, sidecar_relpath
        )
        return sidecar_relpath

    def _new_tombstone_relpath(self, owner: ArtifactOwner, generation: int) -> str:
        owner_hash = hashlib.sha256(
            f"{owner.kb_id}\x00{owner.doc_id}".encode("utf-8")
        ).hexdigest()
        tombstone = (
            f"{self._TOMBSTONE_DIR}/{owner_hash}-g{generation}-{secrets.token_hex(16)}"
        )
        self._validate_tombstone_relative_path(tombstone)
        return tombstone

    @staticmethod
    def _validate_tombstone_relative_path(tombstone_relpath: str) -> str:
        if not _TOMBSTONE_RE.fullmatch(tombstone_relpath):
            raise UnsafeArtifactPath("registry tombstone path violates the internal ABI")
        return tombstone_relpath

    def _ensure_control_directory(self, root_fd: int, name: str) -> int:
        try:
            os.mkdir(name, 0o700, dir_fd=root_fd)
        except FileExistsError:
            pass
        entry_stat = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
        if (
            not stat.S_ISDIR(entry_stat.st_mode)
            or stat.S_ISLNK(entry_stat.st_mode)
            or _has_reparse_point(entry_stat)
        ):
            raise UnsafeArtifactPath("lifecycle control directory is not a real directory")
        return os.open(
            name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=root_fd,
        )

    @staticmethod
    def _split_run(run_relpath: str) -> tuple[str, str]:
        validate_run_relative_path(run_relpath)
        return tuple(run_relpath.split("/"))  # type: ignore[return-value]

    def _run_exists_at(self, root_fd: int, run_relpath: str) -> bool:
        parent_name, leaf_name = self._split_run(run_relpath)
        try:
            parent_fd = os.open(
                parent_name,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=root_fd,
            )
        except FileNotFoundError:
            return False
        try:
            try:
                entry_stat = os.stat(leaf_name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                return False
            self._assert_real_directory_entry(entry_stat)
            return True
        finally:
            os.close(parent_fd)

    def _tombstone_exists_at(self, root_fd: int, tombstone_relpath: str) -> bool:
        self._validate_tombstone_relative_path(tombstone_relpath)
        _, name = tombstone_relpath.split("/", 1)
        tombstone_dir_fd = self._ensure_control_directory(root_fd, self._TOMBSTONE_DIR)
        try:
            try:
                entry_stat = os.stat(name, dir_fd=tombstone_dir_fd, follow_symlinks=False)
            except FileNotFoundError:
                return False
            self._assert_real_directory_entry(entry_stat)
            return True
        finally:
            os.close(tombstone_dir_fd)

    def _rename_run_to_tombstone(
        self, root_fd: int, run_relpath: str, tombstone_relpath: str
    ) -> None:
        parent_name, leaf_name = self._split_run(run_relpath)
        self._validate_tombstone_relative_path(tombstone_relpath)
        _, tombstone_name = tombstone_relpath.split("/", 1)
        parent_fd = os.open(
            parent_name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=root_fd,
        )
        tombstone_dir_fd = self._ensure_control_directory(root_fd, self._TOMBSTONE_DIR)
        try:
            self._assert_real_directory_entry(
                os.stat(leaf_name, dir_fd=parent_fd, follow_symlinks=False)
            )
            try:
                os.stat(tombstone_name, dir_fd=tombstone_dir_fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise UnsafeArtifactPath("persisted tombstone name already exists")
            os.rename(
                leaf_name,
                tombstone_name,
                src_dir_fd=parent_fd,
                dst_dir_fd=tombstone_dir_fd,
            )
        finally:
            os.close(tombstone_dir_fd)
            os.close(parent_fd)

    def _remove_tombstone_tree(self, root_fd: int, tombstone_relpath: str) -> None:
        self._validate_tombstone_relative_path(tombstone_relpath)
        _, name = tombstone_relpath.split("/", 1)
        tombstone_dir_fd = self._ensure_control_directory(root_fd, self._TOMBSTONE_DIR)
        try:
            self._remove_entry_at(tombstone_dir_fd, name)
        finally:
            os.close(tombstone_dir_fd)

    def _remove_entry_at(self, parent_fd: int, name: str) -> None:
        """Remove an entry using fd-relative, no-follow traversal only."""

        entry_stat = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if stat.S_ISLNK(entry_stat.st_mode) or _has_reparse_point(entry_stat):
            raise UnsafeArtifactPath("refusing to remove symlink or reparse-point artifact entry")
        if stat.S_ISDIR(entry_stat.st_mode):
            directory_fd = os.open(
                name,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=parent_fd,
            )
            try:
                with os.scandir(directory_fd) as entries:
                    for entry in entries:
                        if entry.name in {".", ".."}:
                            raise UnsafeArtifactPath("invalid artifact directory entry")
                        self._remove_entry_at(directory_fd, entry.name)
            finally:
                os.close(directory_fd)
            os.rmdir(name, dir_fd=parent_fd)
            return
        if not stat.S_ISREG(entry_stat.st_mode):
            raise UnsafeArtifactPath("refusing to remove non-regular artifact entry")
        if entry_stat.st_nlink != 1:
            raise UnsafeArtifactPath("refusing to remove hard-linked artifact entry")
        # unlink removes the directory entry itself and does not follow a link
        # introduced after the lstat above; a race can only make this fail safe.
        os.unlink(name, dir_fd=parent_fd)

    @staticmethod
    def _assert_real_directory_entry(entry_stat: os.stat_result) -> None:
        if (
            not stat.S_ISDIR(entry_stat.st_mode)
            or stat.S_ISLNK(entry_stat.st_mode)
            or _has_reparse_point(entry_stat)
        ):
            raise UnsafeArtifactPath("artifact directory entry is not a real directory")
