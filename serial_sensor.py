"""Read the Olfy v1 newline-delimited JSON protocol from USB serial devices."""

import json
import time

from .contracts import SensorInfo, UNITS, normalize_sample, validate_info


def _reject_constant(value):
    raise ValueError(f"Invalid JSON number {value}.")


class SerialSensor:
    def __init__(self, port="auto", baud_rate=115200):
        self.connection = None
        self.pending = None
        self.last_sequence = None
        try:
            import serial
            from serial.tools import list_ports
        except ImportError as exc:
            raise RuntimeError("Install serial dependencies first: bash start.sh --serial") from exc
        if port == "auto":
            candidates = [p.device for p in list_ports.comports() if p.vid is not None]
            if len(candidates) != 1:
                raise ValueError("Choose a serial port explicitly unless exactly one USB serial device is connected.")
            port = candidates[0]
        if not isinstance(port, str) or not port or "://" in port:
            raise ValueError("Use a local serial port, such as /dev/cu.usbmodem1234.")
        if isinstance(baud_rate, bool) or not isinstance(baud_rate, int) or not 1200 <= baud_rate <= 2000000:
            raise ValueError("Baud rate must be an integer between 1200 and 2000000.")
        try:
            self.connection = serial.Serial(port, baudrate=baud_rate, timeout=1, write_timeout=1)
            self.connection.reset_input_buffer()
            # Permit startup text while a newly opened microcontroller boots.
            deadline = time.monotonic() + 5
            packet = None
            for _ in range(20):
                if time.monotonic() >= deadline:
                    break
                line = self.connection.readline(16385)
                if not line.strip() or not line.lstrip().startswith(b"{"):
                    continue
                packet = self._decode(line)
                break
            if packet is None:
                raise RuntimeError("No Olfy JSON sample received. Check the baud rate and firmware packet format.")
            units = dict(UNITS)
            supplied_units = packet.get("units", {})
            if not isinstance(supplied_units, dict) or len(supplied_units) > 40:
                raise ValueError("units must be a small object mapping channel names to units.")
            units.update(supplied_units)
            self.info = SensorInfo("serial", packet.get("device_id"), packet.get("profile"),
                                   mode=packet.get("mode", "real"), units=units,
                                   transport={"kind": "usb-serial", "port": port, "baud_rate": baud_rate})
            validate_info(self.info, "real")
            self.pending = self._sample(packet)
        except Exception:
            self.close()
            raise

    @staticmethod
    def _decode(line):
        if len(line) > 16384 or not line.endswith(b"\n"):
            raise ValueError("Serial packet is too large or missing its newline terminator.")
        try:
            packet = json.loads(line.decode("utf-8"), parse_constant=_reject_constant)
        except (ValueError, UnicodeError) as exc:
            raise ValueError("Invalid UTF-8 JSON sensor packet.") from exc
        if not isinstance(packet, dict) or packet.get("type") != "olfy.sample" or type(packet.get("schema_version")) is not int or packet["schema_version"] != 1:
            raise ValueError("Firmware must send type olfy.sample with schema_version 1.")
        return packet

    def _sample(self, packet):
        if packet.get("device_id") != self.info.device_id or packet.get("profile") != self.info.profile:
            raise ValueError("Serial device identity/profile changed. Reconnect and collect a separate scan.")
        if packet.get("mode", "real") != "real":
            raise ValueError("Synthetic packets cannot enter the real workspace.")
        units = packet.get("units", {})
        if not isinstance(units, dict) or any(self.info.units.get(k) != v for k, v in units.items()):
            raise ValueError("Serial channel units changed during the connection.")
        if "source_sequence" not in packet:
            raise ValueError("Firmware must include an increasing source_sequence.")
        sample = normalize_sample(self.info, packet)
        sequence = sample["source_sequence"]
        if self.last_sequence is not None and sequence <= self.last_sequence:
            raise ValueError("Duplicate or backwards source_sequence. Reconnect after a device reset.")
        self.last_sequence = sequence
        return sample

    def read(self, phase, seconds):
        if self.pending is not None:
            sample, self.pending = self.pending, None
            return sample
        line = self.connection.readline(16385)
        if not line:
            raise RuntimeError("Serial sensor timed out. Check the cable and firmware stream.")
        packet = self._decode(line)
        # Discard queued older packets when firmware streams faster than the recorder.
        deadline = time.monotonic() + .05
        for _ in range(100):
            if self.connection.in_waiting <= 0 or time.monotonic() >= deadline:
                break
            next_packet = self._decode(self.connection.readline(16385))
            self._sample(packet)
            packet = next_packet
        return self._sample(packet)

    def close(self):
        if self.connection is not None:
            self.connection.close()
            self.connection = None
