"""Deterministic synthetic data for exercising the software. Not perfume data."""

from datetime import datetime, timedelta, timezone
from .sensors import SimulatedSensor, DEMO_LABELS, PROFILE


def seed_demo(store):
    existing = [s for s in store.list("simulation") if s.get("dataset") == "demo-v1"]
    if existing:
        return {"created": 0, "existing": len(existing)}
    created = 0
    for day in range(4):
        specimens = [(label, "known", rep) for label in DEMO_LABELS for rep in range(3)]
        specimens += [("Unfamiliar demo mixture", "unknown", 0), ("Clean-air control", "blank", 0)]
        for label, kind, rep in specimens:
            metadata = {"label": label, "kind": kind, "group_id": f"demo-day-{day + 1}",
                        "bottle_id": "synthetic-source", "sample_id": f"demo-{day}-{created}",
                        "device_id": "simulator", "profile": PROFILE, "substrate": "simulated",
                        "dose": "simulated", "drydown_min": 0, "notes": "Artificial response curves; not measurements.",
                        "dataset": "demo-v1"}
            scan_id = store.create("simulation", metadata)
            sensor = SimulatedSensor(label, seed=1000 + created, day=day, kind=kind)
            t = 0
            readings = []
            start = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=day, minutes=created * 5)
            for phase, count in (("baseline", 30), ("exposure", 60), ("recovery", 90)):
                for second in range(count):
                    readings.append({"sequence": t,
                        "timestamp": (start + timedelta(seconds=t)).isoformat(), "elapsed_s": t,
                        "phase": phase, "phase_elapsed_s": second, **sensor.read(phase, second)})
                    t += 1
            store.append_many("simulation", scan_id, readings)
            store.finish("simulation", scan_id)
            created += 1
    return {"created": created, "existing": 0}
