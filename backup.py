"""Consistent data snapshots and a restore that never overwrites existing data."""

from contextlib import contextmanager
import fcntl
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import zipfile

from . import __version__
from .storage import now

DATABASES = ("real.sqlite3", "simulation.sqlite3", "catalogue.sqlite3")
MODELS = ("model_real.json", "model_simulation.json")


class WorkspaceLock:
    def __init__(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        self.file = (directory / "workspace.lock").open("a+")
        try:
            fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.file.close()
            raise ValueError("This data folder is already open in Olfy. Use the running app or stop it first.") from None

    def close(self):
        if not self.file.closed:
            fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
            self.file.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def create_backup(store):
    """Caller holds the recorder/mutation lock; no scan may be recording."""
    files = {}
    with tempfile.TemporaryDirectory() as tmp:
        for name in DATABASES:
            destination = Path(tmp) / name
            with sqlite3.connect(store.directory / name) as source, sqlite3.connect(destination) as target:
                source.backup(target)
            files[name] = destination.read_bytes()
    for name in MODELS:
        path = store.directory / name
        if path.exists():
            files[name] = path.read_bytes()
    manifest = {"backup_version": 1, "software_version": __version__, "created_at": now(),
                "files": {name: {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                          for name, data in files.items()},
                "counts": {mode: len(store.list(mode)) for mode in ("real", "simulation")},
                "catalogue": store.catalogue.summary()}
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
        archive.writestr("backup_manifest.json", json.dumps(manifest, indent=2, allow_nan=False))
    return output.getvalue()


def restore_backup(backup_path, directory):
    """Validate in a staging folder, then restore only to a fresh data directory."""
    directory = Path(directory)
    if directory.exists() and any(p.name != "workspace.lock" for p in directory.iterdir()):
        raise ValueError("Restore requires an empty data folder. Choose a new --data-dir; existing recordings are never overwritten.")
    allowed = set(DATABASES + MODELS + ("backup_manifest.json",))
    try:
        with zipfile.ZipFile(backup_path) as archive, tempfile.TemporaryDirectory() as tmp:
            entries = archive.infolist()
            names = [f.filename for f in entries]
            if len(set(names)) != len(names) or set(names) - allowed or not set(DATABASES + ("backup_manifest.json",)) <= set(names):
                raise ValueError("Backup contains missing, duplicate or unsupported files.")
            if sum(f.file_size for f in entries) > 2 * 1024**3:
                raise ValueError("This backup exceeds the 2 GiB local restore limit.")
            manifest = json.loads(archive.read("backup_manifest.json"))
            if manifest.get("backup_version") != 1 or set(manifest.get("files", {})) != set(names) - {"backup_manifest.json"}:
                raise ValueError("Unsupported or incomplete backup manifest.")
            staged = []
            for name, expected in manifest["files"].items():
                data = archive.read(name)
                if len(data) != expected["bytes"] or hashlib.sha256(data).hexdigest() != expected["sha256"]:
                    raise ValueError("Backup checksum failed for " + name)
                path = Path(tmp) / name
                path.write_bytes(data)
                if name in DATABASES:
                    with sqlite3.connect(path) as db:
                        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                            raise ValueError("Backup database integrity check failed for " + name)
                else:
                    json.loads(data)
                staged.append(path)
            directory.mkdir(parents=True, exist_ok=True)
            written = []
            try:
                for path in staged:
                    target = directory / path.name
                    target.write_bytes(path.read_bytes())
                    written.append(target)
            except Exception:
                for target in written:
                    target.unlink(missing_ok=True)
                raise
            return manifest
    except (zipfile.BadZipFile, json.JSONDecodeError, KeyError, TypeError, sqlite3.DatabaseError) as exc:
        raise ValueError("Invalid Olfy backup: " + str(exc)) from exc
