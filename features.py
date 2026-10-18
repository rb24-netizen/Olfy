"""One feature vector per complete independent exposure, never per time sample."""

import hashlib
import json
import numpy as np

from .contracts import UNITS

FEATURE_VERSION = "log-resistance-phase-bins-v1"
REFERENCE_PROTOCOL = "reference-phases-v1"

FEATURE_NAMES = ([f"exposure_bin_{i}" for i in range(1, 5)] +
                 [f"recovery_bin_{i}" for i in range(1, 5)] +
                 ["exposure_min", "exposure_max", "exposure_std", "recovery_end"])

FEATURE_DEFINITIONS = [
    {"name": name, "order": i, "signal": "gas_ohm", "unit": "dimensionless",
     "phase": "recovery" if name.startswith("recovery") else "exposure",
     "calculation": ("Mean normalized log resistance in time quartile " + name[-1]
                     if "_bin_" in name else {
                         "exposure_min": "Minimum normalized log resistance during exposure",
                         "exposure_max": "Maximum normalized log resistance during exposure",
                         "exposure_std": "Population standard deviation during exposure",
                         "recovery_end": "Mean of the final three recovery readings"}[name])}
    for i, name in enumerate(FEATURE_NAMES)]


def profile_definition(sensor, readings=(), sampling_interval_s=1.0):
    """The configuration shared by the catalogue and classifier, excluding identity.

    Preserve observed heater settings: a reused profile name cannot conceal a
    different heater configuration. Units and extra channel declarations also
    participate. Sample-rate changes require compatible new measurements.
    """
    settings = sorted({(r.get("heater_c"), r.get("heater_ms")) for r in readings
                       if r.get("heater_c") is not None or r.get("heater_ms") is not None},
                      key=lambda x: (str(x[0]), str(x[1])))
    if not settings and sensor.get("adapter_id") == "bme688" and sensor.get("profile") == "forced-320C-150ms-1Hz-v1":
        settings = [(320.0, 150.0)]
    return {"adapter_id": sensor["adapter_id"], "profile": sensor["profile"],
            "units": sensor.get("units", UNITS), "sampling_interval_s": float(sampling_interval_s),
            "heater_settings": [{"heater_c": float(c) if c is not None else None,
                                 "heater_ms": float(ms) if ms is not None else None} for c, ms in settings]}


def profile_key(definition):
    return hashlib.sha256(json.dumps(definition, sort_keys=True, allow_nan=False).encode()).hexdigest()[:24]


def scan_profile(scan):
    sensor = scan.get("sensor") or {"adapter_id": scan.get("adapter_id") or
             ("simulation" if scan.get("mode") == "simulation" else "legacy"),
             "profile": scan["profile"], "units": UNITS}
    definition = profile_definition(sensor, scan["readings"], scan.get("sampling_interval_s", 1.0))
    return profile_key(definition), definition


def extract(scan):
    if scan["status"] != "complete":
        raise ValueError("Only completed baseline/exposure/recovery scans can be used.")
    rows = scan["readings"]
    if not rows:
        raise ValueError("Scan has no readings.")
    times = np.array([r["elapsed_s"] for r in rows], dtype=float)
    gas = np.array([r["gas_ohm"] for r in rows], dtype=float)
    if not np.all(np.isfinite(times)) or not np.all(np.diff(times) > 0):
        raise ValueError("Timestamps must be finite and strictly increasing.")
    if not np.all(np.isfinite(gas)) or np.any(gas <= 0):
        raise ValueError("Gas resistance must be finite and positive.")
    stages = {}
    for phase in ("baseline", "exposure", "recovery"):
        indices = [i for i, r in enumerate(rows) if r["phase"] == phase]
        if len(indices) < 8:
            raise ValueError(f"Need at least 8 measurements in {phase}; use longer phases.")
        stages[phase] = indices
    phase_order = [r["phase"] for r in rows]
    expected = sum(([phase] * len(stages[phase]) for phase in stages), [])
    if phase_order != expected:
        raise ValueError("Phases must be contiguous: baseline, exposure, recovery.")
    baseline = float(np.median(gas[stages["baseline"]]))
    normalized = np.log(gas / baseline)
    baseline_noise = float(np.std(normalized[stages["baseline"]]))
    vector = []
    durations = {}
    for phase in ("exposure", "recovery"):
        idx = stages[phase]
        t = times[idx]
        durations[phase] = float(t[-1] - t[0])
        fraction = (t - t[0]) / max(t[-1] - t[0], 1e-9)
        # Time bins, rather than count bins, tolerate small USB scheduling jitter.
        for j in range(4):
            keep = (fraction >= j / 4) & (fraction <= 1 if j == 3 else fraction < (j + 1) / 4)
            if not np.any(keep):
                raise ValueError("A phase has a missing time bin; check sample gaps.")
            vector.append(float(np.mean(normalized[idx][keep])))
    exposure = normalized[stages["exposure"]]
    recovery = normalized[stages["recovery"]]
    vector.extend([float(np.min(exposure)), float(np.max(exposure)),
                   float(np.std(exposure)), float(np.mean(recovery[-3:]))])
    if not np.all(np.isfinite(vector)):
        raise ValueError("Non-finite extracted feature.")
    warnings = []
    if baseline_noise > .05:
        warnings.append("Baseline log-resistance noise exceeds 0.05; inspect warm-up and sampling.")
    if abs(float(np.mean(recovery[-3:]))) > .1:
        warnings.append("Recovery ends more than about 10% from baseline; allow more clearing time.")
    return np.array(vector), {"baseline_ohm": baseline, "baseline_log_std": baseline_noise,
                              "max_abs_exposure_log": float(np.max(np.abs(exposure))),
                              "phase_durations_s": durations, "warnings": warnings}
