"""Safe local backup and restore primitives for Nexus server workspaces."""
from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import uuid
import zipfile
from pathlib import Path, PurePosixPath

MAX_BACKUP_BYTES = 5 * 1024 * 1024 * 1024
CHUNK_SIZE = 1024 * 1024


def _server_root(directory):
    original = Path(directory)
    if original.is_symlink():
        raise ValueError("Server workspace cannot be a symbolic link.")
    root = original.resolve()
    if not root.is_dir():
        raise ValueError("Server workspace does not exist.")
    return root


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while True:
            chunk = stream.read(CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def create_backup(server_directory, backup_directory, backup_id=None):
    root = _server_root(server_directory)
    backup_id = backup_id or str(uuid.uuid4())
    if not backup_id.replace("-", "").isalnum() or len(backup_id) > 64:
        raise ValueError("Invalid backup identifier.")
    destination_root = Path(backup_directory).resolve()
    destination_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(destination_root, 0o700)
    except OSError:
        pass
    final_path = destination_root / (backup_id + ".zip")
    if final_path.exists():
        raise ValueError("Backup identifier already exists.")
    files = []
    total = 0
    for current, dirs, names in os.walk(root, followlinks=False):
        current_path = Path(current)
        dirs[:] = sorted(d for d in dirs if not (current_path / d).is_symlink())
        for name in sorted(names):
            path = current_path / name
            if path.is_symlink():
                continue
            if not path.is_file():
                continue
            total += path.stat().st_size
            if total > MAX_BACKUP_BYTES:
                raise ValueError("Server data exceeds the 5 GB backup limit.")
            files.append(path)
    if shutil.disk_usage(destination_root).free < max(10 * 1024 * 1024, total // 20):
        raise OSError("Not enough free disk space to create a backup safely.")
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".nexus-backup-", suffix=".tmp", dir=str(destination_root), delete=False) as tmp:
            temporary_path = Path(tmp.name)
        with zipfile.ZipFile(temporary_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=3, allowZip64=True) as archive:
            for path in files:
                archive.write(path, arcname=path.relative_to(root).as_posix())
        size = temporary_path.stat().st_size
        if size > MAX_BACKUP_BYTES:
            raise ValueError("Compressed backup exceeds the 5 GB limit.")
        checksum = _sha256(temporary_path)
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, final_path)
        temporary_path = None
        return {"id": backup_id, "filename": final_path.name, "size": size, "sha256": checksum, "files": len(files)}
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def restore_backup(server_directory, backup_file, expected_sha256, backup_directory):
    root_input = Path(server_directory)
    if root_input.is_symlink():
        raise ValueError("Server workspace cannot be a symbolic link.")
    root = root_input.resolve()
    parent = root.parent
    backup_root = Path(backup_directory).resolve()
    candidate = Path(backup_file)
    if candidate.name != candidate.as_posix() or candidate.suffix != ".zip":
        raise ValueError("Invalid backup filename.")
    backup_path = (backup_root / candidate.name).resolve()
    if backup_path.parent != backup_root or not backup_path.is_file() or backup_path.is_symlink():
        raise ValueError("Backup file was not found in the backup store.")
    if not isinstance(expected_sha256, str) or _sha256(backup_path).lower() != expected_sha256.lower():
        raise ValueError("Backup SHA-256 verification failed; restore was cancelled.")
    stage = parent / ("." + root.name + ".restore-" + uuid.uuid4().hex)
    old = parent / ("." + root.name + ".before-restore-" + uuid.uuid4().hex)
    stage.mkdir(mode=0o700)
    try:
        total_uncompressed = 0
        with zipfile.ZipFile(backup_path, "r") as archive:
            members = archive.infolist()
            if len(members) > 200000:
                raise ValueError("Backup contains too many entries.")
            for member in members:
                raw_name = member.filename
                relative = PurePosixPath(raw_name)
                if not raw_name or relative.is_absolute() or "\\" in raw_name or any(part in ("", ".", "..") for part in relative.parts):
                    raise ValueError("Backup contains an unsafe path.")
                mode = (member.external_attr >> 16) & 0o170000
                if mode == 0o120000:
                    raise ValueError("Backup contains a symbolic link; restore was cancelled.")
                total_uncompressed += member.file_size
                if total_uncompressed > MAX_BACKUP_BYTES:
                    raise ValueError("Backup expands beyond the 5 GB restore limit.")
                target = stage.joinpath(*relative.parts)
                resolved = target.resolve()
                if resolved != stage and stage not in resolved.parents:
                    raise ValueError("Backup path escaped the restore directory.")
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member, "r") as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output, length=CHUNK_SIZE)
        if root.exists():
            os.replace(root, old)
        try:
            os.replace(stage, root)
        except Exception:
            if old.exists() and not root.exists():
                os.replace(old, root)
            raise
        if old.exists():
            shutil.rmtree(old)
        return {"restored": True, "files": sum(1 for p in root.rglob("*") if p.is_file()), "backup": backup_path.name}
    finally:
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)
