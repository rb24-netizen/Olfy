"""Preparation tools. Practice stays in a disposable dataset, away from recordings."""

from datetime import date, timedelta
from importlib import metadata
import io
import csv
import json
import platform
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

from . import __version__
from .backup import create_backup, restore_backup
from .demo import seed_demo
from .features import FEATURE_NAMES, FEATURE_VERSION
from .model import predict, train
from .storage import Store

PLAN_KEY = "experiment_plan_v1"


def package_version(name):
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def setup_status(store, recorder):
    """Local checks only: no sensor connection and no artificial data insertion."""
    packages = {name: package_version(name) for name in (
        "numpy", "scikit-learn", "adafruit-blinka", "adafruit-circuitpython-bme680", "hidapi", "pyserial")}
    checks = []
    python_ok = (3, 11) <= sys.version_info[:2] < (3, 14)
    checks.append({"id": "python", "label": "Python", "status": "ready" if python_ok else "action",
                   "detail": platform.python_version()})
    core_ok = bool(packages["numpy"] and packages["scikit-learn"])
    checks.append({"id": "core", "label": "App dependencies", "status": "ready" if core_ok else "action",
                   "detail": "Installed" if core_ok else "Run bash start.sh to install the app dependencies."})
    try:
        with tempfile.TemporaryFile(dir=store.directory) as probe:
            probe.write(b"olfy-write-check")
            probe.flush()
        checks.append({"id": "storage", "label": "Recording folder", "status": "ready", "detail": "Writable"})
    except OSError as exc:
        checks.append({"id": "storage", "label": "Recording folder", "status": "action", "detail": str(exc)})
    database_ok = True
    for name in ("real.sqlite3", "simulation.sqlite3", "catalogue.sqlite3"):
        try:
            uri = (store.directory / name).resolve().as_uri() + "?mode=ro"
            with sqlite3.connect(uri, uri=True, timeout=3) as db:
                if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    database_ok = False
        except sqlite3.Error:
            database_ok = False
    checks.append({"id": "databases", "label": "Data integrity", "status": "ready" if database_ok else "action",
                   "detail": "All three databases checked" if database_ok else "A database needs attention. Preserve the data folder and inspect the error before recording."})
    web = Path(__file__).parent / "web"
    ui_ok = (web / "consumer" / "index.html").is_file()
    checks.append({"id": "interface", "label": "Consumer interface", "status": "ready" if ui_ok else "action",
                   "detail": "Bundled; Node is not required" if ui_ok else "Compiled interface missing. Extract the complete starter ZIP."})
    summary = store.catalogue.summary()
    real = store.list("real")
    simulated = store.list("simulation")
    status = recorder.status()
    bme_ready = all(packages[name] for name in ("adafruit-blinka", "adafruit-circuitpython-bme680", "hidapi"))
    serial_ready = bool(packages["pyserial"])
    return {"software_version": __version__, "checks": checks,
            "software_ready": all(c["status"] == "ready" for c in checks),
            "system": {"os": platform.system(), "architecture": platform.machine(), "python": platform.python_version()},
            "packages": packages, "data_directory": str(store.directory.resolve()),
            "free_bytes": shutil.disk_usage(store.directory).free,
            "catalogue": summary, "real_scans": len(real), "simulation_scans": len(simulated),
            "real_complete_scans": sum(s["status"] == "complete" for s in real),
            "hardware": {"connected": status["connected_mode"] == "real", "sensor": status["sensor"],
                         "bme688_drivers_installed": bme_ready, "serial_driver_installed": serial_ready,
                         "physical_verification": "Not established by software checks"},
            "active_scan": status["active"], "plan": load_plan(store),
            "limits": {"perfume_accuracy_validated": False, "wireless_accessory": False,
                       "quick_capture_identification": False}}


def run_practice():
    """Exercise actual storage/features/model/backup code in a temporary directory."""
    with tempfile.TemporaryDirectory(prefix="olfy-practice-") as root:
        store = Store(Path(root) / "practice")
        seeded = seed_demo(store)
        model = train(store, "simulation", "demo-day-4")
        heldout = [s for s in store.list("simulation") if s["group_id"] == "demo-day-4"]
        known = next(s for s in heldout if s["kind"] == "known")
        unknown = next(s for s in heldout if s["kind"] == "unknown")
        known_scan = store.get("simulation", known["id"])
        known_result = predict(model, known_scan)
        unknown_result = predict(model, store.get("simulation", unknown["id"]))
        store.bookmark("simulation", known["id"], True)
        backup_path = Path(root) / "practice-backup.zip"
        backup_path.write_bytes(create_backup(store))
        restored_dir = Path(root) / "restored"
        restore_backup(backup_path, restored_dir)
        restored = Store(restored_dir)
        backup_ok = (len(restored.list("simulation")) == seeded["created"] and
                     restored.bookmarks("simulation") == [known["id"]] and
                     restored.get("simulation", known["id"])["readings"] == known_scan["readings"] and
                     restored.load_model("simulation")["model_id"] == model["model_id"] and
                     not restored.list("real") and restored.catalogue.summary()["reference_count"] == 0)
        checks = [
            {"id": "samples", "label": "Generated sample storage", "passed": seeded["created"] == 68,
             "detail": f"{seeded['created']} artificial recordings across four collection days"},
            {"id": "features", "label": "Shared sensor features", "passed": len(FEATURE_NAMES) == 12,
             "detail": f"{len(FEATURE_NAMES)} features; {FEATURE_VERSION}"},
            {"id": "holdout", "label": "Independent test split", "passed": all(s["id"] not in model["train_scan_ids"] for s in heldout),
             "detail": "The fourth generated collection day was excluded from training"},
            {"id": "known", "label": "Known generated example", "passed": known_result["decision"] == "match" and known_result["label"] == known["label"],
             "detail": f"{known['label']}: {known_result['label'] or 'no reliable match'}"},
            {"id": "unknown", "label": "Unknown generated control", "passed": unknown_result["decision"] != "match",
             "detail": "Rejected" if unknown_result["decision"] != "match" else "Accepted; inspect the generated-data model"},
            {"id": "backup", "label": "Save, back up and restore", "passed": backup_ok,
             "detail": "Restored readings, saved bookmark and model; real reference catalogue stayed empty"},
        ]
        return {"passed": all(c["passed"] for c in checks), "checks": checks,
                "report": model["report"], "isolated": True,
                "note": "Disposable generated data. Your workspaces and existing models were not changed. This tests the software, not real perfume recognition."}


def load_plan(store):
    with store.connect("real") as db:
        row = db.execute("SELECT value FROM workspace_settings WHERE key=?", (PLAN_KEY,)).fetchone()
    return json.loads(row[0]) if row else None


def save_plan(store, supplied):
    allowed = {"fragrance_ids", "substrate", "dose", "drydown_min", "start_date", "include_unknown_control"}
    if set(supplied) - allowed:
        raise ValueError("Unsupported plan fields.")
    ids = supplied.get("fragrance_ids")
    if not isinstance(ids, list) or not 2 <= len(ids) <= 5 or any(not isinstance(i, str) for i in ids) or len(set(ids)) != len(ids):
        raise ValueError("Choose 2-5 different perfume variants for the first experiment.")
    for fragrance_id in ids:
        store.catalogue.get(fragrance_id)
    unknown = supplied.get("include_unknown_control", False)
    if type(unknown) is not bool:
        raise ValueError("include_unknown_control must be true or false.")
    text = {}
    for key in ("substrate", "dose"):
        value = supplied.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > 120:
            raise ValueError(f"{key} must be 1-120 characters.")
        text[key] = value.strip()
    drydown = supplied.get("drydown_min")
    if type(drydown) not in (float, int) or not 0 <= drydown <= 10080:
        raise ValueError("Drydown must be a finite number between 0 and 10080 minutes.")
    try:
        start = date.fromisoformat(supplied.get("start_date", ""))
    except (TypeError, ValueError):
        raise ValueError("Choose a valid planned first collection date.") from None
    if start.year > 9998:
        raise ValueError("Choose a collection date before the year 9999.")
    plan = {"schema_version": 1, "fragrance_ids": ids, **text, "drydown_min": drydown,
            "start_date": start.isoformat(), "collection_days": [(start + timedelta(days=i)).isoformat() for i in range(3)],
            "replicates_per_perfume_per_day": 3, "include_unknown_control": unknown, "controls_per_day": 1 + int(unknown),
            "phase_targets_s": {"baseline": 30, "exposure": 60, "recovery": 90},
            "note": "Planning defaults, not a validated protocol. Use actual collection dates and a fresh sample for each exposure. The unfamiliar-perfume control is optional; without one, rejection of unfamiliar perfumes remains untested. Allow extra clearing time as needed."}
    with store.connect("real") as db:
        db.execute("INSERT OR REPLACE INTO workspace_settings VALUES (?,?)", (PLAN_KEY, json.dumps(plan, allow_nan=False)))
    return plan


def plan_rows(store):
    plan = load_plan(store)
    if not plan:
        return []
    rows = []
    for group in plan["collection_days"]:
        for fragrance_id in plan["fragrance_ids"]:
            item = store.catalogue.get(fragrance_id)
            for rep in range(1, 4):
                rows.append({"fragrance_id": fragrance_id, "label": item["label"], "kind": "known",
                             "group_id": group, "sample_id": f"{group}-{fragrance_id}-r{rep}",
                             "substrate": plan["substrate"], "dose": plan["dose"], "drydown_min": plan["drydown_min"]})
        controls = [("blank", "Clean-air control")]
        if plan.get("include_unknown_control", True):
            controls.append(("unknown", "Unfamiliar perfume control"))
        for kind, label in controls:
            rows.append({"fragrance_id": "", "label": label, "kind": kind, "group_id": group,
                         "sample_id": f"{group}-{kind}-control", "substrate": plan["substrate"],
                         "dose": "clean air" if kind == "blank" else plan["dose"],
                         "drydown_min": 0 if kind == "blank" else plan["drydown_min"]})
    return rows


def plan_csv(store):
    rows = plan_rows(store)
    if not rows:
        raise ValueError("Save an experiment plan first.")
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=[*rows[0], "bottle_id", "actual_collection_date", "completed", "notes"])
    writer.writeheader()
    for row in rows:
        # Spreadsheet programs must treat user-entered planning text as text.
        row = {key: "'" + value if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")) else value for key, value in row.items()}
        writer.writerow({**row, "notes": "PLANNED ONLY. Verify actual date and conditions before recording."})
    return output.getvalue()
