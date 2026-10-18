"""Versioned, transport-independent sensor contract used by every adapter."""

from dataclasses import asdict, dataclass, field
import math
import json
from typing import Mapping, Protocol

SCHEMA_VERSION = 1
UNITS = {"gas_ohm": "ohm", "temperature_c": "degC", "humidity_pct": "%RH",
         "pressure_hpa": "hPa", "heater_c": "degC", "heater_ms": "ms"}


@dataclass(frozen=True)
class SensorInfo:
    adapter_id: str
    device_id: str
    profile: str
    mode: str = "real"
    schema_version: int = SCHEMA_VERSION
    units: dict = field(default_factory=lambda: dict(UNITS))
    transport: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


class Sensor(Protocol):
    info: SensorInfo

    def read(self, phase: str, seconds: float) -> Mapping:
        """Return one fresh sample using canonical units; raise on failure."""
        ...

    def close(self) -> None:
        """Release resources, including after a partially completed connection."""
        ...


def validate_info(info, expected_mode):
    if not isinstance(info, SensorInfo) or type(info.schema_version) is not int or info.schema_version != SCHEMA_VERSION:
        raise ValueError("Adapter must expose SensorInfo with schema version 1.")
    if info.mode != expected_mode:
        raise ValueError("A simulation adapter cannot be connected as real hardware.")
    for name in ("adapter_id", "device_id", "profile"):
        value = getattr(info, name)
        if not isinstance(value, str) or not value.strip() or len(value) > 120:
            raise ValueError(f"Adapter {name} must be a nonempty string of at most 120 characters.")
    if not isinstance(info.units, dict) or len(info.units) > 40:
        raise ValueError("Adapter units must be a small dictionary.")
    for name, unit in info.units.items():
        if not isinstance(name, str) or not name.isidentifier() or len(name) > 64 or not isinstance(unit, str) or not 0 < len(unit) <= 30:
            raise ValueError("Declare channel names and units as short strings.")
    if info.units.get("gas_ohm") != "ohm":
        raise ValueError("This baseline requires gas resistance in ohms. Add a feature adapter for another signal type.")
    try:
        json.dumps(info.to_dict(), allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise ValueError("SensorInfo must contain finite, JSON-serializable metadata.") from exc


def normalize_sample(info, sample):
    """Whitelist measurements so hardware cannot overwrite host metadata/timing."""
    if not isinstance(sample, Mapping):
        raise ValueError("Sensor sample must be an object.")
    result = {"schema_version": SCHEMA_VERSION}
    for name, unit in UNITS.items():
        value = sample.get(name)
        if value is None:
            if name == "gas_ohm":
                raise ValueError("Sensor sample is missing gas_ohm.")
            continue
        if info.units.get(name) != unit:
            raise ValueError(f"{name} has incompatible units; expected {unit}.")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{name} must be a finite number.")
        if name == "gas_ohm" and value <= 0:
            raise ValueError("Gas resistance must be positive.")
        result[name] = float(value)
    extras = sample.get("extra_channels", {})
    if not isinstance(extras, Mapping) or len(extras) > 32:
        raise ValueError("extra_channels must contain at most 32 declared numeric channels.")
    if extras:
        result["extra_channels"] = {}
        for key, value in extras.items():
            if key in UNITS or key not in info.units:
                raise ValueError(f"Undeclared extra channel: {key}.")
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"Extra channel {key} must be finite.")
            result["extra_channels"][key] = float(value)
    if "source_sequence" in sample:
        sequence = sample["source_sequence"]
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
            raise ValueError("source_sequence must be a nonnegative integer.")
        result["source_sequence"] = sequence
    return result
