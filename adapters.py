"""Adapter registry. Register custom transports without changing the recorder."""

from dataclasses import dataclass

from .contracts import validate_info
from .sensors import BME688Sensor, SimulatedSensor
from .serial_sensor import SerialSensor


@dataclass
class AdapterSpec:
    adapter_id: str
    label: str
    mode: str
    factory: object
    options: tuple = ()


class AdapterRegistry:
    def __init__(self):
        self.specs = {}

    def register(self, spec):
        if not isinstance(spec, AdapterSpec) or spec.mode not in ("real", "simulation") or not callable(spec.factory):
            raise ValueError("Register a valid AdapterSpec with a callable factory.")
        if spec.adapter_id in self.specs:
            raise ValueError("Adapter ID is already registered.")
        self.specs[spec.adapter_id] = spec

    def create(self, adapter_id, config=None):
        if adapter_id not in self.specs:
            raise ValueError("Unknown adapter. Query /api/v1/adapters for registered adapters.")
        if config is None:
            config = {}
        if not isinstance(config, dict):
            raise ValueError("Adapter config must be an object.")
        spec = self.specs[adapter_id]
        unsupported = set(config) - set(spec.options)
        if unsupported:
            raise ValueError("Unsupported adapter options: " + ", ".join(sorted(unsupported)))
        sensor = spec.factory(**config)
        try:
            validate_info(sensor.info, spec.mode)
            if sensor.info.adapter_id != spec.adapter_id:
                raise ValueError("Adapter ID disagrees with SensorInfo.")
        except Exception:
            sensor.close()
            raise
        return sensor

    def list(self):
        return [{"adapter_id": s.adapter_id, "label": s.label, "mode": s.mode,
                 "options": list(s.options)} for s in self.specs.values()]


def default_registry():
    registry = AdapterRegistry()
    registry.register(AdapterSpec("bme688", "BME688 / MCP2221 USB bridge", "real", BME688Sensor, ("address", "device_id")))
    registry.register(AdapterSpec("serial", "USB serial / Olfy JSON firmware", "real", SerialSensor, ("port", "baud_rate")))
    registry.register(AdapterSpec("simulation", "Artificial response generator", "simulation", SimulatedSensor, ("label", "seed", "day", "kind")))
    return registry


def inventory(registry):
    ports, bridges, warnings = [], [], []
    try:
        from serial.tools import list_ports
        ports = [{"port": p.device, "description": p.description, "usb": p.vid is not None,
                  "serial_number": p.serial_number} for p in sorted(list_ports.comports())]
    except ImportError:
        warnings.append("USB serial support is optional: bash start.sh --serial")
    except Exception as exc:
        warnings.append(f"Could not list serial ports: {exc}")
    try:
        import hid
        bridges = [{"serial_number": str(p.get("serial_number") or ""),
                    "product": str(p.get("product_string") or "MCP2221")}
                   for p in hid.enumerate(0x04D8, 0x00DD)]
    except ImportError:
        warnings.append("BME688 support is optional: bash start.sh --hardware")
    except Exception as exc:
        warnings.append(f"Could not enumerate MCP2221 bridges: {exc}")
    return {"adapters": registry.list(), "serial_ports": ports, "usb_bridges": bridges,
            "warnings": warnings, "schema_version": 1}
