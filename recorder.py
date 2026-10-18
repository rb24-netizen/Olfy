"""Single-device, 1 Hz acquisition with explicit sample phases."""

from collections import Counter
import math
import threading
import time
import uuid

from .adapters import default_registry
from .contracts import normalize_sample, validate_info
from .storage import now


class Recorder:
    def __init__(self, store, interval=1.0, registry=None):
        self.store = store
        self.registry = registry or default_registry()
        self.interval = interval
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.sensor = None
        self.sensor_mode = None
        self.connected_at = None
        self.active = None
        self.latest = None
        self.error = None
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def connect_real(self, address="auto"):
        return self.connect("bme688", {"address": address})

    def connect(self, adapter_id, config=None):
        with self.lock:
            if self.active:
                raise ValueError("Finish or abort the current recording first.")
            self._disconnect()
            candidate = self.registry.create(adapter_id, config)
            try:
                validate_info(candidate.info, "real")
                first = normalize_sample(candidate.info, candidate.read("baseline", 0))
            except Exception:
                candidate.close()
                raise
            self.sensor = candidate
            self.latest = {"timestamp": now(), "phase": "baseline", "phase_elapsed_s": 0, **first}
            self.sensor_mode = candidate.info.mode
            self.connected_at = time.monotonic()
            self.error = None
            return candidate.info.to_dict()

    def _disconnect(self):
        sensor = self.sensor
        self.sensor = self.sensor_mode = self.connected_at = self.latest = None
        if sensor:
            sensor.close()

    def disconnect(self):
        with self.lock:
            if self.active:
                raise ValueError("Finish or abort the current recording first.")
            self._disconnect()

    def start(self, mode, supplied, quick_duration=None):
        with self.lock:
            if self.active:
                raise ValueError("A recording is already running.")
            if mode not in ("simulation", "real"):
                raise ValueError("Choose simulation or real mode.")
            if quick_duration is not None:
                if mode != "real" or isinstance(quick_duration, bool) or not isinstance(quick_duration, (int, float)) or not math.isfinite(quick_duration) or not 5 <= quick_duration <= 60:
                    raise ValueError("Quick capture requires real mode and a duration between 5 and 60 seconds.")
            if mode == "simulation" and self.sensor_mode == "real":
                raise ValueError("Disconnect the real sensor before switching to simulation.")
            supplied = self.store.catalogue.bind(supplied, mode, quick=quick_duration is not None)
            metadata = {}
            for key in ("fragrance_id", "label", "group_id", "bottle_id", "sample_id", "device_id", "substrate", "dose", "notes"):
                value = str(supplied.get(key, "")).strip()
                if len(value) > (1000 if key == "notes" else 120):
                    raise ValueError(f"{key} is too long.")
                metadata[key] = value
            kind = supplied.get("kind", "known")
            if kind not in ("known", "unknown", "blank"):
                raise ValueError("Invalid sample kind.")
            if not metadata["label"] or not metadata["group_id"]:
                raise ValueError("Label and collection day are required.")
            metadata["sample_id"] = metadata["sample_id"] or uuid.uuid4().hex[:12]
            try:
                drydown = float(supplied.get("drydown_min", 0))
            except (ValueError, TypeError) as exc:
                raise ValueError("Drydown must be a number of minutes.") from exc
            if not math.isfinite(drydown) or not 0 <= drydown <= 10080:
                raise ValueError("Drydown must be between 0 and 10080 minutes.")
            metadata.update(kind=kind, drydown_min=drydown)
            if quick_duration is not None:
                metadata.update(kind="unknown", acquisition_protocol="quick-capture-v1", capture_duration_s=float(quick_duration))
            else:
                metadata["acquisition_protocol"] = "reference-phases-v1"
            if mode == "real":
                if self.sensor_mode != "real" or self.sensor is None:
                    raise ValueError("Connect the real sensor first, then let it warm up in clean air.")
                if metadata["device_id"] and metadata["device_id"] != self.sensor.info.device_id:
                    raise ValueError("Device ID differs from the connected sensor. Use its detected ID or reconnect with an assigned ID.")
                if not metadata["bottle_id"]:
                    raise ValueError("Bottle ID is required for real scans.")
                if supplied.get("warmup_ack") is not True:
                    raise ValueError("Confirm you completed sensor conditioning and warm-up.")
            else:
                metadata["device_id"] = "simulator"
                self.sensor = self.registry.create("simulation", {"label": metadata["label"], "kind": kind})
                self.sensor_mode = "simulation"
                self.connected_at = time.monotonic()
            metadata.update(device_id=self.sensor.info.device_id, profile=self.sensor.info.profile,
                            adapter_id=self.sensor.info.adapter_id, schema_version=1,
                            sampling_interval_s=self.interval,
                            sensor=self.sensor.info.to_dict())
            scan_id = self.store.create(mode, metadata)
            self.active = {"id": scan_id, "mode": mode, "phase": "baseline",
                           "started": time.monotonic(), "phase_started": time.monotonic(),
                           "counts": Counter(), "sequence": 0, "readings": []}
            if quick_duration is not None:
                self.active.update(phase="exposure", capture_mode="quick", target_seconds=float(quick_duration))
            self.error = None
            return scan_id

    def _require_active(self, mode=None, scan_id=None):
        if not self.active:
            raise ValueError("No recording is running.")
        if mode is not None and mode != self.active["mode"]:
            raise ValueError("Recording belongs to another workspace.")
        if scan_id is not None and scan_id != self.active["id"]:
            raise ValueError("Stale scan ID. Refresh status; this action cannot affect another scan.")

    def advance(self, mode=None, scan_id=None):
        with self.lock:
            self._require_active(mode, scan_id)
            if self.active.get("capture_mode") == "quick":
                raise ValueError("Quick capture ends automatically. Use Abort to cancel it.")
            phase = self.active["phase"]
            if self.active["counts"][phase] < 8:
                raise ValueError("Wait for at least 8 measurements before changing phases.")
            if phase == "recovery":
                raise ValueError("Use Finish to complete this recording.")
            self.active["phase"] = "exposure" if phase == "baseline" else "recovery"
            self.active["phase_started"] = time.monotonic()

    def finish(self, abort=False, mode=None, scan_id=None):
        with self.lock:
            self._require_active(mode, scan_id)
            active = self.active
            if active.get("capture_mode") == "quick" and not abort:
                raise ValueError("Quick capture ends automatically after its requested duration.")
            if not abort and (active["phase"] != "recovery" or
                              any(active["counts"][p] < 8 for p in ("baseline", "exposure", "recovery"))):
                raise ValueError("Complete all three phases with at least 8 measurements each.")
            self.store.finish(active["mode"], active["id"], "aborted" if abort else "complete")
            self.active = None
            if self.sensor_mode == "simulation":
                self._disconnect()
            return active["id"]

    def status(self):
        with self.lock:
            active = self.active
            return {"connected_mode": self.sensor_mode, "error": self.error, "latest": self.latest,
                    "sensor": self.sensor.info.to_dict() if self.sensor else None,
                    "connected_seconds": (round(time.monotonic() - self.connected_at)
                                          if self.connected_at is not None else 0),
                    "active": ({"id": active["id"], "mode": active["mode"], "phase": active["phase"],
                                "capture_mode": active.get("capture_mode", "reference"),
                                "target_seconds": active.get("target_seconds"),
                                "elapsed_s": round(time.monotonic() - active["started"], 1),
                                "phase_elapsed_s": round(time.monotonic() - active["phase_started"], 1),
                                "counts": dict(active["counts"]), "readings": active["readings"][-600:]}
                               if active else None)}

    def _run(self):
        next_read = time.monotonic() + self.interval
        while not self.stop.wait(max(0, next_read - time.monotonic())):
            next_read = time.monotonic() + self.interval
            with self.lock:
                if self.sensor is None:
                    continue
                active = self.active
                phase = active["phase"] if active else "baseline"
                t = time.monotonic()
                seconds = t - active["phase_started"] if active else 0
                try:
                    values = normalize_sample(self.sensor.info, self.sensor.read(phase, seconds))
                    reading = {"timestamp": now(), "phase": phase, "phase_elapsed_s": seconds, **values}
                    self.latest = reading
                    if active:
                        reading.update(sequence=active["sequence"], elapsed_s=t - active["started"])
                        self.store.append(active["mode"], active["id"], reading)
                        active["sequence"] += 1
                        active["counts"][phase] += 1
                        active["readings"].append(reading)
                        if len(active["readings"]) > 600:
                            del active["readings"][:-600]
                        if active.get("capture_mode") == "quick" and seconds >= active["target_seconds"]:
                            self.store.finish(active["mode"], active["id"], "captured")
                            self.active = None
                except Exception as exc:
                    self.error = str(exc)
                    if active:
                        try:
                            self.store.finish(active["mode"], active["id"], "error")
                        except Exception as storage_error:
                            self.error += "; could not mark the recording: " + str(storage_error)
                    self.active = None
                    try:
                        self._disconnect()
                    except Exception as close_error:
                        self.error += "; device close failed: " + str(close_error)

    def close(self):
        self.stop.set()
        self.thread.join(timeout=5)
        with self.lock:
            if self.active:
                self.store.finish(self.active["mode"], self.active["id"], "aborted")
                self.active = None
            self._disconnect()
