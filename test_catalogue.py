"""Temporary software fixtures only; no perfume measurements are produced."""
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen

from olfy.catalogue import Catalogue, FEATURE_SCHEME
from olfy.client import OlfyClient, OlfyError
from olfy.contracts import SensorInfo, UNITS
from olfy.features import FEATURE_NAMES
from olfy.recorder import Recorder
from olfy.server import make_server
from olfy.storage import Store
from test_integration import StubSensor, stub_registry


def fixture_reference(store, fragrance, *, mode="real", status="complete", profile="unit-fixture-v1", device="fixture-01", count=8):
    """Deterministic unit-test numbers, never exported as a perfume fingerprint."""
    info = SensorInfo("stub", device, profile, mode=mode,
                      units={**UNITS, "second_gas_ohm": "ohm"})
    sid = store.create(mode, {"fragrance_id": fragrance["fragrance_id"], "label": fragrance["label"],
        "kind": "known", "group_id": "fixture-day", "bottle_id": "fixture-bottle",
        "sample_id": "fixture-" + device + profile, "device_id": device, "profile": profile,
        "acquisition_protocol": "reference-phases-v1", "sensor": info.to_dict(),
        "substrate": "test fixture", "dose": "test fixture", "drydown_min": 5})
    rows = []
    for phase, resistance in (("baseline", 100000), ("exposure", 80000), ("recovery", 95000)):
        for n in range(count):
            rows.append({"sequence": len(rows), "elapsed_s": len(rows), "phase": phase,
                "phase_elapsed_s": n, "gas_ohm": resistance, "temperature_c": 23,
                "humidity_pct": 40, "pressure_hpa": 1013, "heater_c": 320, "heater_ms": 150,
                "extra_channels": {"second_gas_ohm": 90000}})
    store.append_many(mode, sid, rows)
    store.finish(mode, sid, status)
    return sid


class CatalogueTests(unittest.TestCase):
    def test_seed_has_exactly_50_distinct_variants_and_no_invented_signals(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = Catalogue(tmp)
            data = c.snapshot()
            self.assertEqual(data["summary"], {"perfume_count": 50, "measured_count": 0,
                "reference_count": 0, "usable_count": 0, "pending_count": 50})
            self.assertEqual(len({f["fragrance_id"] for f in data["fragrances"]}), 50)
            self.assertTrue(all(f["fingerprints_url"] is None and f["global_sales_rank"] is None
                                and f["concentration_pct"] is None for f in data["fragrances"]))
            self.assertTrue(all(f["measurement_status"] == "pending" for f in data["fragrances"]))
            self.assertFalse(any("Body Milk" in f["name"] for f in data["fragrances"]))
            self.assertEqual(data["measurements"], [])
            self.assertEqual(data["feature_definition"]["names"], FEATURE_NAMES)
            self.assertEqual(data["sensor_profiles"][0]["settings"]["heater_c"], 320)
            self.assertTrue(all(s["sort_code"] == "BEST_SELLING" and s["market"] == "US" for s in data["sources"]))

    def test_references_only_bind_real_known_full_scans_and_canonicalize_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            c = store.catalogue
            f = c.snapshot()["fragrances"][0]
            supplied = {"fragrance_id": f["fragrance_id"], "label": "wrong arbitrary label"}
            self.assertEqual(c.bind(supplied, "real")["label"], f["label"])
            for mode, quick, kind in (("simulation", False, "known"), ("real", True, "known"), ("real", False, "unknown"), ("real", False, "blank")):
                with self.subTest(mode=mode, quick=quick, kind=kind), self.assertRaises(ValueError):
                    c.bind({**supplied, "kind": kind}, mode, quick)
            for invalid in ("missing", 123, False):
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    c.bind({"fragrance_id": invalid}, "real")
            recorder = Recorder(store)
            try:
                with self.assertRaisesRegex(ValueError, "not simulation"):
                    recorder.start("simulation", {**supplied, "group_id": "fixture"})
                self.assertEqual(store.list("simulation"), [])
            finally:
                recorder.close()

    def test_complete_real_reference_is_indexed_with_units_conditions_and_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            f = store.catalogue.snapshot()["fragrances"][0]
            first = fixture_reference(store, f)
            second = fixture_reference(store, f, profile="different-heater-fixture-v1")
            data = store.catalogue.snapshot(f["fragrance_id"])
            self.assertEqual(data["summary"]["measured_count"], 1)
            self.assertEqual(data["summary"]["usable_count"], 2)
            self.assertEqual(len(data["measurements"]), 2)
            self.assertEqual({m["scan_id"] for m in data["measurements"]}, {first, second})
            self.assertEqual(len({m["profile_key"] for m in data["measurements"]}), 2)
            m = data["measurements"][0]
            self.assertEqual(set(m["features"]), set(FEATURE_NAMES))
            self.assertEqual(m["feature_scheme"], FEATURE_SCHEME)
            self.assertEqual(m["channel_summary"]["baseline"]["gas_ohm"]["median"], 100000)
            self.assertEqual(m["channel_summary"]["exposure"]["second_gas_ohm"]["unit"], "ohm")
            self.assertEqual(m["conditions"]["bottle_id"], "fixture-bottle")
            self.assertEqual(m["raw_database"], "real.sqlite3")
            # Re-opening and re-indexing never duplicates or replaces a measurement.
            reopened = Store(tmp)
            reopened.catalogue.index_reference(reopened.get("real", first))
            self.assertEqual(reopened.catalogue.summary()["reference_count"], 2)
            self.assertIn(f["fragrance_id"], reopened.export_csv("real"))

    def test_partial_quick_and_simulated_scans_cannot_become_measured_fingerprints(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            f = store.catalogue.snapshot()["fragrances"][0]
            fixture_reference(store, f, mode="simulation")
            fixture_reference(store, f, status="aborted")
            fixture_reference(store, f, status="captured")
            self.assertEqual(store.catalogue.summary()["reference_count"], 0)
            fixture_reference(store, f, count=2)
            data = store.catalogue.snapshot(f["fragrance_id"])
            self.assertEqual(data["summary"]["measured_count"], 0)
            self.assertEqual(data["fragrances"][0]["measurement_status"], "needs_review")
            self.assertIsNone(data["measurements"][0]["features"])

    def test_catalogue_api_export_and_real_recorder_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = StubSensor()
            app, server = make_server(tmp, 0, registry=stub_registry(source))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            client = OlfyClient(base)
            try:
                f = client.catalogue()["fragrances"][0]
                self.assertEqual(len(client.catalogue(f["fragrance_id"])["fragrances"]), 1)
                with self.assertRaises(OlfyError):
                    client.start_scan({"fragrance_id": f["fragrance_id"], "group_id": "fixture"}, mode="simulation")
                client.connect_sensor("stub")
                sid = client.start_scan({"fragrance_id": f["fragrance_id"], "group_id": "fixture-day",
                    "bottle_id": "fixture-bottle", "warmup_ack": True})["scan_id"]
                self.assertEqual(client.get_scan(sid)["label"], f["label"])
                self.assertEqual(client.get_scan(sid)["fragrance_id"], f["fragrance_id"])
                client.finish_scan(sid, abort=True)
                self.assertEqual(client.catalogue()["summary"]["reference_count"], 0)
                with urlopen(base + "/api/v1/catalogue/export") as response:
                    self.assertEqual(response.headers["Content-Type"], "application/vnd.sqlite3")
                    target = Path(tmp) / "download.sqlite3"
                    target.write_bytes(response.read())
                with sqlite3.connect(target) as db:
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM fragrances").fetchone()[0], 50)
                    self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                with self.assertRaises(HTTPError):
                    urlopen(base + "/api/v1/catalogue?id=missing")
            finally:
                server.shutdown(); server.server_close(); app.recorder.close(); thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
