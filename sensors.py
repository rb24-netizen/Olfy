"""A synthetic signal generator and an optional BME688/MCP2221 adapter."""

import math
import os
import random
import time

from .contracts import SensorInfo, UNITS

PROFILE = "forced-320C-150ms-1Hz-v1"
DEMO_LABELS = ["Demo A", "Demo B", "Demo C", "Demo D", "Demo E"]
# These arbitrary response shapes are NOT measurements or chemical models.
SHAPES = [(.25, 8, 15), (.45, 16, 28), (.65, 24, 42), (.86, 10, 60), (1.05, 35, 18)]


class SimulatedSensor:
    def __init__(self, label="Demo A", seed=None, day=0, kind="known"):
        self.info = SensorInfo("simulation", "simulator", PROFILE, mode="simulation")
        self.rng = random.Random(seed)
        if kind == "blank":
            self.amplitude, self.rise, self.fall = .003, 10, 20
        elif kind == "unknown":
            self.amplitude, self.rise, self.fall = 1.8, 3, 110
        else:
            index = DEMO_LABELS.index(label) if label in DEMO_LABELS else sum(map(ord, label)) % 5
            self.amplitude, self.rise, self.fall = SHAPES[index]
        self.amplitude *= self.rng.uniform(.94, 1.06)
        self.baseline = 110000 * self.rng.uniform(.8, 1.2) * (1 + day * .025)
        self.signal = 0.0
        self.recovery_start = 0.0
        self.last_phase = "baseline"
        self.temperature = 23 + day * .15 + self.rng.uniform(-.3, .3)
        self.humidity = 42 + day + self.rng.uniform(-1, 1)

    def read(self, phase, seconds):
        if phase == "exposure":
            self.signal = -self.amplitude * (1 - math.exp(-seconds / self.rise))
        elif phase == "recovery":
            if self.last_phase != "recovery":
                self.recovery_start = self.signal
            self.signal = self.recovery_start * math.exp(-seconds / self.fall)
        else:
            self.signal = 0
        self.last_phase = phase
        return {"gas_ohm": self.baseline * math.exp(self.signal + self.rng.gauss(0, .004)),
                "temperature_c": self.temperature + self.rng.gauss(0, .04),
                "humidity_pct": self.humidity + self.rng.gauss(0, .15),
                "pressure_hpa": 1013 + self.rng.gauss(0, .05),
                "heater_c": 320, "heater_ms": 150}

    def close(self):
        pass


class BME688Sensor:
    """Real hardware adapter, API-reviewed but not tested on a physical sensor here.

    Blinka uses the MCP2221 USB bridge. The driver name includes BME680 but
    Adafruit supplies this library for the BME688 breakout too. This deliberately
    starts with ONE fixed heater setting; it is not a Bosch AI-Studio gas scan.
    """
    def __init__(self, address="auto", device_id=""):
        if isinstance(address, str) and address != "auto":
            address = int(address, 0)
        if address not in ("auto", 0x76, 0x77):
            raise ValueError("BME688 address must be auto, 0x76 or 0x77.")
        os.environ["BLINKA_MCP2221"] = "1"
        try:
            import board
            import adafruit_bme680
            import hid
        except ImportError as exc:
            raise RuntimeError("Install hardware dependencies first: bash start.sh --hardware") from exc
        self.i2c = None
        try:
            bridges = hid.enumerate(0x04D8, 0x00DD)
            if not bridges:
                raise RuntimeError("No MCP2221 USB bridge detected. Check that the cable carries data.")
            if len(bridges) != 1:
                raise RuntimeError("Multiple MCP2221 bridges detected. Connect only the intended bridge.")
            self.i2c = board.I2C()
            if address == "auto":
                deadline = time.monotonic() + 1
                while not self.i2c.try_lock():
                    if time.monotonic() > deadline:
                        raise RuntimeError("The I2C bus is busy; close other sensor applications.")
                    time.sleep(.01)
                try:
                    candidates = [a for a in self.i2c.scan() if a in (0x76, 0x77)]
                finally:
                    self.i2c.unlock()
                if len(candidates) != 1:
                    raise RuntimeError("Expected one BME688 at 0x76 or 0x77. Check the QT cable, or choose an address explicitly if both are present.")
                address = candidates[0]
            self.sensor = adafruit_bme680.Adafruit_BME680_I2C(self.i2c, address=address, refresh_rate=1)
            if not self.sensor.set_gas_heater(320, 150):
                raise RuntimeError("The driver could not configure the gas heater.")
            bridge_serial = str(bridges[0].get("serial_number") or "")
            identity = device_id or (f"bme688-{bridge_serial}-{address:02x}" if bridge_serial else f"bme688-mcp2221-{address:02x}")
            self.info = SensorInfo("bme688", identity, PROFILE,
                                   transport={"kind": "usb-i2c", "address": hex(address),
                                              "bridge_serial": bridge_serial,
                                              "identity_source": "assigned" if device_id else "usb-bridge"})
        except Exception as exc:
            self.close()
            raise RuntimeError(f"Sensor connection failed. Check the USB data cable, QT cable, address and MCP2221 adapter. Detail: {exc}") from exc

    def read(self, phase, seconds):
        values = {"gas_ohm": float(self.sensor.gas),
                  "temperature_c": float(self.sensor.temperature),
                  "humidity_pct": float(self.sensor.relative_humidity),
                  "pressure_hpa": float(self.sensor.pressure),
                  "heater_c": 320, "heater_ms": 150}
        if not all(math.isfinite(v) for v in values.values()) or values["gas_ohm"] <= 0:
            raise RuntimeError("Sensor returned an invalid measurement. Recording stopped; no synthetic values substituted.")
        return values

    def close(self):
        if self.i2c is not None:
            try:
                self.i2c.deinit()
            except Exception:
                pass
            self.i2c = None
