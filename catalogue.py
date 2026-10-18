"""Sourced perfume identities and fingerprints indexed from real reference scans.

The seed contains no measured signals. A fingerprint is one complete physical
exposure, with its device, profile, conditions and raw scan ID kept attached.
"""

from collections import defaultdict
from contextlib import contextmanager
import json
import math
from pathlib import Path
import sqlite3
from statistics import mean, median
import tempfile

from .contracts import UNITS
from .features import (FEATURE_NAMES, FEATURE_DEFINITIONS, FEATURE_VERSION, REFERENCE_PROTOCOL,
                       extract, profile_definition, profile_key, scan_profile)
from .sensors import PROFILE

FEATURE_SCHEME = FEATURE_VERSION
HERE = Path(__file__).parent


def encoded(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True)


class Catalogue:
    def __init__(self, directory):
        self.path = Path(directory) / "catalogue.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        seed = json.loads((HERE / "reference_catalogue.json").read_text())
        with self.connect() as db:
            db.executescript((HERE / "catalogue_schema.sql").read_text())
            for key in ("schema_version", "catalogue_id", "title", "selection_scope", "selection_method"):
                db.execute("INSERT OR IGNORE INTO catalogue_metadata VALUES (?,?)", (key, encoded(seed[key])))
            for source in seed["sources"]:
                db.execute("INSERT OR IGNORE INTO sources VALUES (?,?,?,?,?,?,?)", (
                    source["source_id"], source["retailer"], source["market"], source["source_url"],
                    source["retrieved_at"], source["snapshot_sha256"], encoded(source)))
            for item in seed["fragrances"]:
                db.execute("INSERT OR IGNORE INTO fragrances VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (
                    item["fragrance_id"], item["selection_order"], item["brand"], item["name"], item["label"],
                    item["concentration_label"], None, item["source_id"], item["product_id"],
                    item["product_url"], item["source_display_position"], encoded(item)))
            db.execute("INSERT OR REPLACE INTO catalogue_metadata VALUES ('schema_version','2')")
            for feature in FEATURE_DEFINITIONS:
                db.execute("INSERT OR IGNORE INTO feature_definitions VALUES (?,?,?,?,?,?)", (
                    FEATURE_SCHEME, feature["name"], feature["order"], feature["signal"],
                    feature["unit"], feature["calculation"]))
            self._profile(db, {"adapter_id": "bme688", "profile": PROFILE, "units": UNITS})

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")
        try:
            with db:
                yield db
        finally:
            db.close()

    def get(self, fragrance_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM fragrances WHERE fragrance_id=?", (fragrance_id,)).fetchone()
        if row is None:
            raise ValueError("Unknown fragrance_id. Choose an entry from the reference catalogue.")
        return json.loads(row["details_json"])

    def bind(self, supplied, mode, quick=False):
        """Canonicalize a selected identity; never label synthetic curves with it."""
        fragrance_id = supplied.get("fragrance_id", "")
        if fragrance_id is None:
            return {**supplied, "fragrance_id": ""}
        if fragrance_id == "":
            return supplied
        if not isinstance(fragrance_id, str) or len(fragrance_id) > 120:
            raise ValueError("fragrance_id must be a short string.")
        if mode != "real":
            raise ValueError("Catalogue perfume references require real measurements, not simulation.")
        if quick or supplied.get("kind", "known") != "known":
            raise ValueError("Catalogue references require a known baseline/exposure/recovery scan in Lab.")
        item = self.get(fragrance_id)
        return {**supplied, "fragrance_id": fragrance_id, "label": item["label"]}

    @staticmethod
    def _profile(db, sensor, definition=None):
        definition = definition or profile_definition(sensor)
        key = profile_key(definition)
        settings = ({"heater_c": 320, "heater_ms": 150, "nominal_rate_hz": 1,
                     "measurement_mode": "forced", "signal": "single gas resistance channel"}
                    if sensor["adapter_id"] == "bme688" and sensor["profile"] == PROFILE
                    else {"signal": "Adapter-declared profile; inspect per-reading heater settings."})
        settings["comparison_definition"] = definition
        db.execute("INSERT OR IGNORE INTO sensor_profiles VALUES (?,?,?,?,?)", (
            key, sensor["adapter_id"], sensor["profile"], encoded(sensor["units"]), encoded(settings)))
        return key

    @staticmethod
    def _channels(scan, units):
        values = defaultdict(lambda: defaultdict(list))
        for row in scan["readings"]:
            channels = {**row, **row.get("extra_channels", {})}
            for name in units:
                value = channels.get(name)
                if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
                    values[row["phase"]][name].append(value)
        return {phase: {name: {"unit": units[name], "count": len(items), "min": min(items),
                              "max": max(items), "mean": mean(items), "median": median(items)}
                        for name, items in channels.items()} for phase, channels in values.items()}

    def index_reference(self, scan):
        """Called after raw storage commits. Quick, partial and synthetic scans skip indexing."""
        if (scan.get("mode") != "real" or scan.get("kind") != "known" or
                scan.get("status") != "complete" or
                scan.get("acquisition_protocol") != REFERENCE_PROTOCOL or not scan.get("fragrance_id")):
            return False
        item = self.get(scan["fragrance_id"])
        if scan.get("label") != item["label"]:
            raise ValueError("Reference scan label differs from its catalogue identity.")
        sensor = scan.get("sensor", {})
        if not all(sensor.get(k) for k in ("adapter_id", "device_id", "profile", "units")):
            raise ValueError("Reference scan must retain its sensor identity and units.")
        if sensor.get("mode") != "real" or sensor["units"].get("gas_ohm") != "ohm":
            raise ValueError("Reference scan must come from a real gas-resistance adapter.")
        features, quality, status = None, {}, "usable"
        try:
            vector, quality = extract(scan)
            features = encoded(dict(zip(FEATURE_NAMES, vector.tolist())))
        except ValueError as exc:
            status, quality = "needs_review", {"warnings": [str(exc)]}
        conditions = {k: scan.get(k) for k in (
            "group_id", "bottle_id", "sample_id", "substrate", "dose", "drydown_min", "notes")}
        with self.connect() as db:
            _, definition = scan_profile(scan)
            key = self._profile(db, sensor, definition)
            db.execute("INSERT OR IGNORE INTO reference_measurements VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                scan["id"], scan["fragrance_id"], scan["created_at"], sensor["device_id"], key,
                REFERENCE_PROTOCOL, FEATURE_SCHEME, status, features,
                encoded(self._channels(scan, sensor["units"])), encoded(conditions), encoded(quality),
                encoded(sensor), "real.sqlite3"))
            # Earlier releases used a different name for this same extractor.
            # Rebuild the derived index from immutable raw scans during migration.
            db.execute("UPDATE reference_measurements SET profile_key=?,feature_scheme=? WHERE scan_id=?",
                       (key, FEATURE_SCHEME, scan["id"]))
            if features:
                db.executemany("INSERT OR IGNORE INTO reference_features VALUES (?,?,?,?)",
                               [(scan["id"], FEATURE_SCHEME, name, value)
                                for name, value in json.loads(features).items()])
            db.executemany("INSERT OR IGNORE INTO reference_samples VALUES (?,?,?,?,?,?,?,?,?,?,?)", [
                (scan["id"], r["sequence"], r["elapsed_s"], r["phase"], r.get("gas_ohm"),
                 r.get("temperature_c"), r.get("humidity_pct"), r.get("pressure_hpa"),
                 r.get("heater_c"), r.get("heater_ms"), encoded(r)) for r in scan["readings"]])
        return True

    def summary(self):
        with self.connect() as db:
            row = db.execute("""SELECT COUNT(*) AS perfume_count,
                COALESCE(SUM(measurement_status='measured'),0) AS measured_count,
                COALESCE(SUM(reference_count),0) AS reference_count,
                COALESCE(SUM(usable_count),0) AS usable_count FROM catalogue_progress""").fetchone()
        return {**dict(row), "pending_count": row["perfume_count"] - row["measured_count"]}

    def snapshot(self, fragrance_id=None):
        with self.connect() as db:
            metadata = {r["key"]: json.loads(r["value"]) for r in db.execute("SELECT * FROM catalogue_metadata")}
            rows = db.execute("""SELECT f.details_json,p.reference_count,p.usable_count,p.measurement_status
                FROM fragrances f JOIN catalogue_progress p USING(fragrance_id) ORDER BY f.selection_order""").fetchall()
            items = [{**json.loads(r["details_json"]), "reference_count": r["reference_count"],
                      "usable_count": r["usable_count"], "measurement_status": r["measurement_status"]} for r in rows]
            for item in items:
                item.pop("measured_fingerprint", None)
                item["fingerprints_url"] = "/api/v1/catalogue?id=" + item["fragrance_id"] if item["reference_count"] else None
            sources = [json.loads(r["details_json"]) for r in db.execute("SELECT * FROM sources")]
            profiles = [{"profile_key": r["profile_key"], "adapter_id": r["adapter_id"], "profile": r["profile_id"],
                         "channels": json.loads(r["channels_json"]), "settings": json.loads(r["settings_json"])}
                        for r in db.execute("SELECT * FROM sensor_profiles")]
            measurements = []
            if fragrance_id:
                items = [f for f in items if f["fragrance_id"] == fragrance_id]
                if not items:
                    raise ValueError("Unknown fragrance_id.")
                for r in db.execute("SELECT * FROM reference_measurements WHERE fragrance_id=? ORDER BY measured_at", (fragrance_id,)):
                    record = dict(r)
                    for key in ("features", "channel_summary", "conditions", "quality", "sensor"):
                        value = record.pop(key + "_json")
                        record[key] = json.loads(value) if value is not None else None
                    record["raw_scan_url"] = "/api/v1/scan?mode=real&id=" + record["scan_id"]
                    record["sample_count"] = db.execute("SELECT COUNT(*) FROM reference_samples WHERE scan_id=?", (record["scan_id"],)).fetchone()[0]
                    record["samples_url"] = "/api/v1/catalogue/samples?id=" + record["scan_id"]
                    measurements.append(record)
        return {**metadata, "summary": self.summary(), "sources": sources, "fragrances": items,
                "sensor_profiles": profiles, "measurements": measurements,
                "feature_definition": {"scheme": FEATURE_SCHEME, "names": FEATURE_NAMES,
                    "parameters": FEATURE_DEFINITIONS,
                    "normalization": "ln(gas_ohm / median clean-air baseline gas_ohm)",
                    "unit": "dimensionless", "protocol": REFERENCE_PROTOCOL,
                    "environment_channels_used_for_classification": False},
                "measurement_note": "Measured means at least one complete reference scan; it does not establish identification accuracy. Each scan retains its own device, profile and conditions. No molecular composition or inferred ingredient fingerprint is stored."}

    def samples(self, scan_id):
        with self.connect() as db:
            exists = db.execute("SELECT fragrance_id,profile_key FROM reference_measurements WHERE scan_id=?", (scan_id,)).fetchone()
            if not exists:
                raise ValueError("Reference measurement not found.")
            rows = db.execute("SELECT payload_json FROM reference_samples WHERE scan_id=? ORDER BY sequence", (scan_id,)).fetchall()
        return {"scan_id": scan_id, "fragrance_id": exists["fragrance_id"], "profile_key": exists["profile_key"],
                "readings": [json.loads(r["payload_json"]) for r in rows]}

    def readiness(self, store, mode="real"):
        """Explain collection coverage; counts are software requirements, not accuracy."""
        items = self.snapshot()["fragrances"]
        cohorts = defaultdict(list)
        for s in store.list(mode):
            if s["status"] != "complete":
                continue
            scan = store.get(mode, s["id"])
            try:
                extract(scan)
                key, definition = scan_profile(scan)
            except ValueError:
                continue
            cohorts[key].append(scan)
        result = []
        for key, scans in cohorts.items():
            known = [s for s in scans if s["kind"] == "known"]
            labels = sorted({s["label"] for s in known})
            days = sorted({s["group_id"] for s in scans})
            candidates = []
            for day in days:
                training = [s for s in known if s["group_id"] != day]
                heldout = [s for s in known if s["group_id"] == day]
                if len(labels) >= 2 and {s["label"] for s in heldout} == set(labels) and all(
                        sum(s["label"] == label for s in training) >= 3 and
                        len({s["group_id"] for s in training if s["label"] == label}) >= 2 for label in labels):
                    candidates.append(day)
            result.append({"profile_key": key, "definition": scan_profile(scans[0])[1],
                           "scan_ids": [s["id"] for s in scans],
                           "labels": labels, "scan_count": len(scans), "collection_days": days,
                           "candidate_test_days": candidates,
                           "control_count": sum(s["kind"] != "known" for s in scans),
                           "label_progress": [{"label": label, "scans": sum(s["label"] == label for s in known),
                               "days": len({s["group_id"] for s in known if s["label"] == label})} for label in labels]})
        return {"mode": mode, "cohorts": result, "catalogue_count": len(items), "feature_version": FEATURE_VERSION,
                "note": "Candidate test days satisfy minimum collection counts only. Training still checks sample independence, protocol, timings and compatible conditions. Counts do not establish accuracy."}

    def export_bytes(self):
        """SQLite backup includes committed WAL contents, unlike copying the main file."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "catalogue.sqlite3"
            with self.connect() as source, sqlite3.connect(target) as destination:
                source.backup(destination)
            return target.read_bytes()
