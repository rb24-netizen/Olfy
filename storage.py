"""Append-only raw scans in separate real and simulation SQLite databases."""

import csv
import io
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .catalogue import Catalogue

MODES = {"simulation", "real"}


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        for mode in MODES:
            with self.connect(mode) as db:
                db.executescript("""
                CREATE TABLE IF NOT EXISTS scans (
                    id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
                    status TEXT NOT NULL, metadata TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS readings (
                    scan_id TEXT NOT NULL, sequence INTEGER NOT NULL,
                    payload TEXT NOT NULL, PRIMARY KEY(scan_id, sequence),
                    FOREIGN KEY(scan_id) REFERENCES scans(id));
                CREATE TABLE IF NOT EXISTS bookmarks (
                    scan_id TEXT PRIMARY KEY REFERENCES scans(id),
                    saved_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS model_runs (
                    model_id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
                    payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS workspace_settings (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL);
                """)
                # Preserve interrupted measurements, but never treat them as complete.
                db.execute("UPDATE scans SET status='interrupted' WHERE status='recording'")
        self.catalogue = Catalogue(self.directory)
        self.index_errors = []
        for mode in MODES:
            existing = self.load_model(mode)
            if existing:
                self._archive_model(mode, existing)
        # Repair an index if the process stopped after committing a completed raw scan.
        for scan in self.list("real"):
            if scan.get("fragrance_id") and scan["status"] == "complete":
                self._index_reference(scan["id"])

    def _index_reference(self, scan_id):
        try:
            self.catalogue.index_reference(self.get("real", scan_id))
        except (ValueError, sqlite3.Error, OSError) as exc:
            self.index_errors.append({"scan_id": scan_id, "error": str(exc)})

    @contextmanager
    def connect(self, mode):
        if mode not in MODES:
            raise ValueError("Mode must be simulation or real.")
        db = sqlite3.connect(self.directory / f"{mode}.sqlite3", timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, mode, metadata):
        scan_id = uuid.uuid4().hex
        metadata = dict(metadata, mode=mode)
        with self.connect(mode) as db:
            db.execute("INSERT INTO scans VALUES (?,?,?,?)",
                       (scan_id, now(), "recording", json.dumps(metadata, allow_nan=False)))
        return scan_id

    def append(self, mode, scan_id, reading):
        self.append_many(mode, scan_id, [reading])

    def append_many(self, mode, scan_id, readings):
        with self.connect(mode) as db:
            db.executemany("INSERT INTO readings VALUES (?,?,?)",
                           [(scan_id, r["sequence"], json.dumps(r, allow_nan=False)) for r in readings])

    def finish(self, mode, scan_id, status="complete"):
        if status not in {"complete", "captured", "aborted", "error"}:
            raise ValueError("Invalid scan status.")
        with self.connect(mode) as db:
            db.execute("UPDATE scans SET status=? WHERE id=?", (status, scan_id))
        if mode == "real" and status == "complete":
            self._index_reference(scan_id)

    def list(self, mode):
        with self.connect(mode) as db:
            rows = db.execute("""SELECT s.*, COUNT(r.sequence) AS sample_count
                FROM scans s LEFT JOIN readings r ON s.id=r.scan_id
                GROUP BY s.id ORDER BY s.created_at DESC, s.id""").fetchall()
        return [{**json.loads(r["metadata"]), "id": r["id"], "created_at": r["created_at"],
                 "status": r["status"], "sample_count": r["sample_count"]} for r in rows]

    def get(self, mode, scan_id):
        with self.connect(mode) as db:
            scan = db.execute("SELECT * FROM scans WHERE id=?", (scan_id,)).fetchone()
            if scan is None:
                raise ValueError("Scan not found in this workspace.")
            rows = db.execute("SELECT payload FROM readings WHERE scan_id=? ORDER BY sequence",
                              (scan_id,)).fetchall()
        return {**json.loads(scan["metadata"]), "id": scan["id"], "created_at": scan["created_at"],
                "status": scan["status"],
                "readings": [json.loads(r["payload"]) for r in rows]}

    def export_csv(self, mode):
        out = io.StringIO(newline="")
        columns = ["mode", "scan_id", "status", "fragrance_id", "label", "kind", "group_id", "bottle_id",
                   "sample_id", "device_id", "profile", "acquisition_protocol", "capture_duration_s", "substrate", "dose", "drydown_min",
                   "sequence", "timestamp", "elapsed_s", "phase", "phase_elapsed_s",
                   "gas_ohm", "temperature_c", "humidity_pct", "pressure_hpa", "heater_c",
                   "heater_ms", "adapter_id", "schema_version", "source_sequence", "extra_channels", "sensor"]
        writer = csv.DictWriter(out, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for summary in self.list(mode):
            scan = self.get(mode, summary["id"])
            for reading in scan["readings"]:
                row = {**scan, **reading, "scan_id": scan["id"]}
                for key in ("extra_channels", "sensor"):
                    if isinstance(row.get(key), dict):
                        row[key] = json.dumps(row[key], separators=(",", ":"))
                # Spreadsheet programs can execute cells starting with these characters.
                row = {k: ("'" + v if isinstance(v, str) and v.startswith(("=", "+", "-", "@")) else v)
                       for k, v in row.items()}
                writer.writerow(row)
        return out.getvalue()

    def bookmarks(self, mode):
        with self.connect(mode) as db:
            return [r["scan_id"] for r in db.execute("SELECT scan_id FROM bookmarks ORDER BY saved_at")]

    def bookmark(self, mode, scan_id, saved=True):
        if type(saved) is not bool:
            raise ValueError("saved must be true or false.")
        scan = self.get(mode, scan_id)
        if scan["status"] not in ("complete", "captured"):
            raise ValueError("Only finished recordings can be saved to the collection.")
        with self.connect(mode) as db:
            if saved:
                db.execute("INSERT OR IGNORE INTO bookmarks VALUES (?,?)", (scan_id, now()))
            else:
                db.execute("DELETE FROM bookmarks WHERE scan_id=?", (scan_id,))
        return self.bookmarks(mode)

    def model_path(self, mode):
        if mode not in MODES:
            raise ValueError("Invalid workspace.")
        return self.directory / f"model_{mode}.json"

    def save_model(self, mode, payload):
        self._archive_model(mode, payload)
        target = self.model_path(mode)
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2, allow_nan=False))
        temporary.replace(target)

    def _archive_model(self, mode, payload):
        with self.connect(mode) as db:
            db.execute("INSERT OR IGNORE INTO model_runs VALUES (?,?,?)",
                       (payload["model_id"], payload["created_at"], json.dumps(payload, allow_nan=False)))

    def model_runs(self, mode):
        with self.connect(mode) as db:
            rows = db.execute("SELECT payload FROM model_runs ORDER BY created_at DESC").fetchall()
        return [{key: p.get(key) for key in ("model_id", "created_at", "classes", "heldout_group", "signal_profile_key", "report", "data_digest")}
                for row in rows for p in [json.loads(row["payload"])]]

    def model_run(self, mode, model_id):
        with self.connect(mode) as db:
            row = db.execute("SELECT payload FROM model_runs WHERE model_id=?", (model_id,)).fetchone()
        if not row:
            raise ValueError("Model run not found in this workspace.")
        return json.loads(row["payload"])

    def load_model(self, mode):
        path = self.model_path(mode)
        return json.loads(path.read_text()) if path.exists() else None
